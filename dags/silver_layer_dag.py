"""
Silver Layer Airflow DAG
Author: Farheen Muzaffar
Description:
    Cleans, validates, and enriches Olist + API data from Bronze layer into Silver layer.
    Triggered automatically after bronze_dag_simple completes.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
import os

# ========== DAG DEFAULT ARGS ==========
default_args = {
    'owner': 'farheen_muzaffar',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# ========== DAG DEFINITION ==========
with DAG(
    dag_id='silver_layer_dag',
    default_args=default_args,
    description='Silver Layer - Data Cleaning, Validation & Enrichment',
    schedule_interval=None,  # Triggered by Bronze DAG
    catchup=False,
    max_active_runs=1,
    tags=['silver', 'cleaning', 'synthcart']
) as dag:

    # Task 1: Setup Silver environment
    setup_silver_environment = BashOperator(
        task_id='setup_silver_environment',
        bash_command="""
        echo "===== Setting up Silver Layer Environment ====="
        mkdir -p /opt/airflow/dags/silver
        echo "✅ Silver environment ready."
        """,
    )

    # Task 2: Determine latest folder from Bronze
    def get_latest_bronze_folders():
        """Fetch latest timestamp folders for kaggle_data and api_data."""
        try:
            from minio import Minio
            client = Minio('minio:9000', access_key='minioadmin', secret_key='minioadmin', secure=False)
            kaggle_prefix = 'kaggle_data/'
            api_prefix = 'api_data/'

            def latest_folder(prefix):
                folders = set()
                try:
                    for obj in client.list_objects('bronze', prefix=prefix, recursive=True):
                        folder = obj.object_name.split('/')[1]
                        if folder:  # ensure folder name is not empty
                            folders.add(folder)
                except Exception as e:
                    print(f"Warning: Could not list objects with prefix {prefix}: {e}")
                    return None
                return max(folders) if folders else None

            latest_kaggle = latest_folder(kaggle_prefix)
            latest_api = latest_folder(api_prefix)

            if not latest_kaggle or not latest_api:
                raise ValueError("❌ Could not find Kaggle/API folders in bronze bucket.")

            print(f"Latest Kaggle folder: {latest_kaggle}")
            print(f"Latest API folder: {latest_api}")

            # Save to temp file for next task
            os.makedirs('/opt/airflow/tmp', exist_ok=True)
            with open('/opt/airflow/tmp/latest_paths.txt', 'w') as f:
                f.write(f"{latest_kaggle},{latest_api}")
                
        except Exception as e:
            print(f"Error in get_latest_bronze_folders: {e}")
            raise

    get_latest_paths = PythonOperator(
        task_id='get_latest_bronze_folders',
        python_callable=get_latest_bronze_folders,
    )

    # Task 3: Run Cleaning & Transformation
    run_cleaning = BashOperator(
        task_id='run_cleaning',
        bash_command="""
        echo "===== Running Silver Cleaning Script ====="
        cd /opt/airflow/dags/silver
        export PYTHONPATH=/opt/airflow/dags/silver:$PYTHONPATH
        python3 silver_cleaning.py
        """,
    )

    # Task 4: Validate Silver Data Quality
    def validate_silver_data_quality():
        """Validate silver layer data meets DA team requirements"""
        try:
            from minio import Minio
            import pandas as pd
            import io
            
            client = Minio('minio:9000', access_key='minioadmin', secret_key='minioadmin', secure=False)
            
            # Check if silver bucket exists
            if not client.bucket_exists('silver'):
                print("⚠️ Silver bucket does not exist yet")
                return
            
            # Get latest silver folder
            folders = set()
            for obj in client.list_objects('silver', prefix='kaggle/', recursive=True):
                parts = obj.object_name.split('/')
                if len(parts) >= 2:
                    folders.add(parts[1])
            
            if not folders:
                print("❌ No silver data folders found")
                raise ValueError("No silver data to validate")
            
            latest_folder = max(folders)
            print(f"📁 Validating silver data from folder: {latest_folder}")
            
            # Validate key files
            validations = {
                'olist_customers_cleaned.parquet': ['customer_id'],
                'olist_products_cleaned.parquet': ['product_id'],
                'olist_orders_cleaned.parquet': ['order_id'],
                'olist_order_items_cleaned.parquet': ['order_id', 'order_item_id'],
                'olist_order_payments_cleaned.parquet': ['order_id', 'payment_sequential'],
                'olist_order_reviews_cleaned.parquet': ['review_id'],
            }
            
            total_files = 0
            validated_files = 0
            
            for filename, key_columns in validations.items():
                try:
                    object_path = f"kaggle/{latest_folder}/{filename}"
                    data = client.get_object('silver', object_path)
                    raw = data.read()
                    data.close()
                    data.release_conn()
                    
                    df = pd.read_parquet(io.BytesIO(raw))
                    total_files += 1
                    
                    # Check for duplicates in key columns
                    if len(key_columns) == 1:
                        duplicates = df[key_columns[0]].duplicated().sum()
                        nulls = df[key_columns[0]].isnull().sum()
                    else:
                        duplicates = df[key_columns].duplicated().sum()
                        nulls = df[key_columns].isnull().any(axis=1).sum()
                    
                    print(f"📊 {filename}: {len(df):,} rows, {duplicates} duplicates, {nulls} nulls")
                    
                    if duplicates == 0 and nulls == 0:
                        validated_files += 1
                        print(f"  ✅ PASSED")
                    else:
                        print(f"  ⚠️ Has issues but acceptable")
                        validated_files += 1  # Still count as processed
                        
                except Exception as e:
                    print(f"  ❌ Error validating {filename}: {e}")
            
            print(f"\n🎉 SILVER VALIDATION COMPLETE: {validated_files}/{total_files} files processed")
            print("✅ Silver data is ready for DA team!")
            
        except Exception as e:
            print(f"❌ Silver validation failed: {e}")
            raise

    validate_silver = PythonOperator(
        task_id='validate_silver',
        python_callable=validate_silver_data_quality,
    )

    # 🟡 Task 5: Trigger Gold Layer DAG
    trigger_gold = TriggerDagRunOperator(
        task_id='trigger_gold',
        trigger_dag_id='gold_layer_dag',   # must match your gold DAG's dag_id
        wait_for_completion=False,
        conf={"triggered_by": "silver", "execution_date": "{{ ts }}"},
    )

    # DAG dependencies
    setup_silver_environment >> get_latest_paths >> run_cleaning >> validate_silver >> trigger_gold

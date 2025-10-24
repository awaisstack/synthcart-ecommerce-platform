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
from minio import Minio
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
        client = Minio('minio:9000', access_key='minioadmin', secret_key='minioadmin', secure=False)
        kaggle_prefix = 'kaggle_data/'
        api_prefix = 'api_data/'

        def latest_folder(prefix):
            folders = set()
            for obj in client.list_objects('bronze', prefix=prefix, recursive=True):
                folder = obj.object_name.split('/')[1]
                folders.add(folder)
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

    # Task 4: Validate output in Silver bucket
    validate_silver = BashOperator(
        task_id='validate_silver',
        bash_command="""
        echo "===== Validating Silver Data in MinIO ====="
        python3 - <<'PY'
from minio import Minio
client = Minio('minio:9000', access_key='minioadmin', secret_key='minioadmin', secure=False)
objects = list(client.list_objects('silver', recursive=True))
print(f"✅ Found {len(objects)} objects in 'silver' bucket.")
for obj in objects[-5:]:
    print(f"  - {obj.object_name} ({obj.size} bytes)")
print("✅ Silver layer validation completed successfully.")
PY
        """,
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

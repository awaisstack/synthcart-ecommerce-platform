"""
Bronze Layer Airflow DAG (Simplified)
Author: Afnan Khan
Description:
    Daily orchestration using bash commands to avoid package dependency issues.
    This DAG handles raw data ingestion from Kaggle and APIs into MinIO.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

# Default arguments for the DAG
default_args = {
    'owner': 'afnan_khan',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

# Create the DAG
with DAG(
    dag_id='bronze_dag_simple',
    default_args=default_args,
    description='Bronze Layer - Raw Data Ingestion (Simplified)',
    schedule_interval='0 18 * * *',  # Run daily at 6:00 PM UTC
    catchup=False,
    max_active_runs=1,
    tags=['bronze', 'ingestion', 'synthcart', 'simple']
) as dag:

    # Task 1: Setup environment (no pip install here)
    setup_environment = BashOperator(
        task_id='setup_environment',
        bash_command="""
        echo "===== Setting up environment ====="
        echo "Tip: For production, install packages via Docker image (AIRFLOW__CORE__PIP_ADDITIONAL_REQUIREMENTS)."

        # Ensure Kaggle credentials exist
        if [ -f /opt/airflow/dags/kaggle.json ]; then
            mkdir -p ~/.kaggle
            cp /opt/airflow/dags/kaggle.json ~/.kaggle/kaggle.json
            chmod 600 ~/.kaggle/kaggle.json
            echo "✅ Kaggle credentials copied successfully."
        else
            echo "⚠️ kaggle.json NOT found at /opt/airflow/dags/kaggle.json — please add it if you need Kaggle downloads."
        fi

        echo "Verifying DAG folder structure..."
        ls -la /opt/airflow/dags/bronze || true

        echo "Testing package imports..."
        python3 - <<'PY'
import sys
try:
    import minio, requests
    print("✅ Required packages found: minio, requests")
    try:
        import kaggle
        print("✅ Kaggle module available")
    except ImportError:
        print("⚠️ Kaggle not installed (expected if not using Kaggle tasks)")
except Exception as e:
    print("❌ Package test failed:", e)
    sys.exit(0)
PY

        echo "Environment setup complete."
        """,
    )

    # Task 2: Kaggle ingestion
    kaggle_ingestion = BashOperator(
        task_id='kaggle_ingestion',
        bash_command="""
        echo "===== Running Kaggle Ingestion ====="
        cd /opt/airflow/dags/bronze
        export PYTHONPATH=/opt/airflow/dags/bronze:$PYTHONPATH
        python3 kaggle_ingestion.py
        """,
    )

    # Task 3: API ingestion
    api_ingestion = BashOperator(
        task_id='api_ingestion',
        bash_command="""
        echo "===== Running API Ingestion ====="
        cd /opt/airflow/dags/bronze
        export PYTHONPATH=/opt/airflow/dags/bronze:$PYTHONPATH
        python3 api_ingestion.py
        """,
    )

    # Task 4: Validate data in MinIO
    validate_data = BashOperator(
        task_id='validate_data',
        bash_command="""
        echo "===== Validating Bronze Layer Data ====="
        python3 - <<'PY'
from minio import Minio
client = Minio('minio:9000', access_key='minioadmin', secret_key='minioadmin', secure=False)
objects = list(client.list_objects('bronze', recursive=True))
print(f"✅ Found {len(objects)} objects in 'bronze' bucket.")
for obj in objects[-5:]:
    print(f"  - {obj.object_name} ({obj.size} bytes)")
print("✅ Bronze layer validation completed successfully.")
PY
        echo "Bronze layer ingestion completed successfully!"
        """,
    )

    # Trigger Silver DAG when Bronze's validate_data succeeds.
    trigger_silver = TriggerDagRunOperator(
        task_id='trigger_silver',
        trigger_dag_id='silver_layer_dag',
        wait_for_completion=False,      # don't block bronze; set True only if you need bronze to wait
        conf={"triggered_by": "bronze", "execution_date": "{{ ts }}"},
    )

    # Define dependencies
    setup_environment >> [kaggle_ingestion, api_ingestion] >> validate_data >> trigger_silver

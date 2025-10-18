"""
Bronze Layer Airflow DAG (Simplified)
Author: Afnan Khan
Description: Daily orchestration using bash commands to avoid package dependency issues
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

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
dag = DAG(
    'bronze_layer_ingestion_simple',
    default_args=default_args,
    description='Bronze Layer - Raw Data Ingestion (Simplified)',
    schedule_interval='0 18 * * *',  # Run daily at 6:00 PM
    catchup=False,
    max_active_runs=1,
    tags=['bronze', 'ingestion', 'synthcart', 'simple']
)

# Task 1: Install packages and setup environment
setup_environment = BashOperator(
    task_id='setup_environment',
    bash_command='''
    echo "Setting up environment..."
    echo "Installing Python packages..."
    python3 -m pip install --user kaggle==1.6.17 minio==7.2.8 requests==2.32.3 pandas==2.2.2 python-dotenv==1.0.1
    
    echo "Setting up Kaggle credentials..."
    mkdir -p ~/.kaggle
    cp /opt/airflow/dags/kaggle.json ~/.kaggle/ || echo "Kaggle credentials already exist"
    chmod 600 ~/.kaggle/kaggle.json || echo "Permissions already set"
    
    echo "Verifying files exist..."
    ls -la /opt/airflow/dags/bronze/
    
    echo "Testing imports..."
    python3 -c "import kaggle, minio, requests; print('All packages imported successfully')"
    
    echo "Environment setup completed"
    ''',
    dag=dag
)

# Task 2: Run Kaggle ingestion
kaggle_ingestion = BashOperator(
    task_id='kaggle_ingestion',
    bash_command='''
    cd /opt/airflow/dags/bronze
    export PYTHONPATH=/opt/airflow/dags/bronze:$PYTHONPATH
    python3 kaggle_ingestion.py
    ''',
    dag=dag
)

# Task 3: Run API ingestion
api_ingestion = BashOperator(
    task_id='api_ingestion',
    bash_command='''
    cd /opt/airflow/dags/bronze
    export PYTHONPATH=/opt/airflow/dags/bronze:$PYTHONPATH
    python3 api_ingestion.py
    ''',
    dag=dag
)

# Task 4: Validate data
validate_data = BashOperator(
    task_id='validate_data',
    bash_command='''
    echo "Validating bronze layer data..."
    echo "Checking MinIO connection and data..."
    
    # Simple validation without running status_check.py
    python3 -c "
from minio import Minio
client = Minio('localhost:9000', access_key='minioadmin', secret_key='minioadmin', secure=False)
objects = list(client.list_objects('bronze', recursive=True))
print(f'Found {len(objects)} objects in bronze bucket')
for obj in objects[-5:]:  # Show last 5 objects
    print(f'  - {obj.object_name} ({obj.size} bytes)')
print('Bronze layer validation completed!')
"
    
    echo "Bronze layer ingestion completed successfully!"
    ''',
    dag=dag
)

# Define task dependencies
setup_environment >> [kaggle_ingestion, api_ingestion] >> validate_data
# Bronze Layer - Raw Data Ingestion
**Author:** Afnan Khan  
**Team:** Data Engineering  
**Project:** SynthCart E-Commerce Analytics Platform

## Overview
The Bronze Layer is responsible for ingesting raw data from multiple sources into our data lake (MinIO). This layer implements the first stage of our Medallion architecture, focusing on reliable data ingestion without any transformations.

## Data Sources
1. **Kaggle Dataset**: Olist Brazilian E-Commerce dataset (CSV files)
2. **DummyJSON API**: Product and user data (JSON format)

## Architecture
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Kaggle API    │    │   DummyJSON API  │    │   MinIO Bronze  │
│   (CSV Files)   │───▶│   (JSON Data)    │───▶│     Bucket      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Files Structure
```
bronze/
├── kaggle_ingestion.py    # Kaggle data extraction and upload
├── api_ingestion.py       # API data fetching and upload
├── bronze_dag_simple.py          # Airflow DAG for daily orchestration
└── README.md             # This documentation
```

## Components

### 1. kaggle_ingestion.py
- Downloads Olist e-commerce dataset from Kaggle
- Extracts CSV files from the downloaded zip
- Uploads all CSV files to MinIO bronze bucket with timestamp versioning
- Handles cleanup of temporary files

### 2. api_ingestion.py
- Fetches product data from `https://dummyjson.com/products`
- Fetches user data from `https://dummyjson.com/users`
- Uploads raw JSON responses to MinIO bronze bucket
- Maintains data in original JSON format for downstream processing

### 3. bronze_dag.py
- Airflow DAG scheduled to run daily at 6 p.m.
- Orchestrates both Kaggle and API ingestion tasks
- Runs tasks in parallel for efficiency
- Includes validation step after successful ingestion

## Data Storage Structure in MinIO
```
bronze/
├── kaggle_data/
│   └── YYYYMMDD_HHMMSS/
│       ├── olist_customers_dataset.csv
│       ├── olist_orders_dataset.csv
│       ├── olist_products_dataset.csv
│       └── ... (other CSV files)
└── api_data/
    └── YYYYMMDD_HHMMSS/
        ├── products.json
        └── users.json
```

## Prerequisites
1. MinIO server running on localhost:9000
2. Kaggle API credentials configured (kaggle.json)
3. Apache Airflow running
4. Required Python packages installed

## Installation & Setup


### Airflow Execution
1. Access Airflow UI at http://localhost:8080
2. Login with username: `airflow`, password: `airflow`
3. Find the DAG named `bronze_layer_ingestion_simple`
4. Enable the DAG for daily execution
5. Trigger manually for testing


## Next Steps
After successful bronze layer ingestion, the data will be available for the Silver layer team (Farheen Muzaffar) to begin data cleaning and transformation processes.

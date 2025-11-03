SynthCart E-Commerce Data Engineering Pipeline
Overview
This project simulates a modern data engineering architecture for an e-commerce platform, collaboratively built by the Data Engineering (DE) and Data Analysis (DA) teams. It follows the Medallion Architecture—Bronze → Silver → Gold—within a fully containerized Docker environment.

AArchitecture Components
Layer	Tool	Purpose
Data Lake	MinIO	Stores raw, cleaned, and curated data
Workflow Orchestration	Apache Airflow	Automates ETL pipelines across all layers
Data Warehouse	PostgreSQL	Stores final business-ready tables
BI Layer	Power BI	Used by DA team for dashboards
Infrastructure	Docker Compose	Containerized setup for reproducibility
Team Contributions
Layer	Contributor(s)	Role
Bronze	Afnan Khan	Raw data ingestion 
Silver	Farheen Muzaffar & Awais	Data cleaning and validation
Gold	 Awais	Aggregation and star-schema modeling and setup
DAGs Pipeline	Afnan Khan	Airflow orchestration and scheduling
Project Structure
Code
├── dags/
│   ├── bronze_dag_simple.py
│   ├── silver_layer_dag.py
│   └── gold_dag.py
├── minio-data/
│   ├── bronze/
│   ├── silver/
│   └── gold/
├── gold_exports/
│   ├── gold_dump.sql
│   ├── *.parquet files
├── docker-compose.yaml
├── README.md
How It Works
Bronze Layer
Source: Kaggle datasets + DummyJSON API

Process: Raw ingestion

Storage: MinIO /bronze/

Owner: Afnan Khan

Silver Layer
Process: Data cleaning and validation using PySpark

Storage: MinIO /silver/

Owners: Farheen Muzaffar & Awais

Gold Layer
Process: Aggregation into star-schema tables:

dim_customers, dim_sellers, dim_products, dim_date, fact_orders

Storage: MinIO /gold/ and optionally PostgreSQL

Owners: Awais

DAGs Pipeline
Tool: Apache Airflow setup

DAGs: Separate for each layer

Owner: Awais khan

Verification Checklist
Tool	Check Method
Docker	docker ps
Airflow	http://localhost:8080
MinIO	http://localhost:9001
PostgreSQL	pgAdmin or Power BI
📊 Final Deliverables
Format	Location	Purpose
SQL Dump	/gold_exports/	PostgreSQL import
Parquet	/gold_exports/	

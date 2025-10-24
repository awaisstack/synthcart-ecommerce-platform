# SynthCart E-Commerce Data Engineering Platform

## Overview
This project simulates a modern data engineering architecture for an e-commerce platform, built collaboratively by the Data Engineering (DE) and Data Analysis (DA) teams.

It implements an end-to-end Medallion Architecture (Bronze → Silver → Gold) using modern open-source tools inside a fully containerized Docker environment.

## Architecture Components

| Layer | Tool | Description |
|-------|------|-------------|
| Data Lake | MinIO | Object storage for raw → cleaned → curated data |
| Workflow Orchestration | Apache Airflow | Automates ETL pipelines (Bronze, Silver, Gold) |
| Data Warehouse | PostgreSQL | Stores final business-ready tables |
| BI Layer | Power BI | Used by DA team for interactive dashboards |
| Infrastructure | Docker Compose | Containerized setup for full reproducibility |

## Setup Instructions (Windows)

### Step 1: Prerequisites
Before starting, ensure you have:
- Docker Desktop (running)
- VS Code (recommended)
- Internet connection

### Step 2: Clone the Repository
Open PowerShell and run:
```bash
cd Desktop
git clone https://github.com/awaisstack/synthcart-ecommerce-platform.git
cd synthcart-ecommerce-platform
```

### Step 3: Start the Environment
Make sure Docker Desktop is running, then execute:
```bash
docker compose up
```

This will automatically:
- Start PostgreSQL, Redis, MinIO, and Airflow
- Connect all services together
- Run in a self-contained local environment

### Step 4: Access the Services

| Service | URL | Username | Password |
|---------|-----|----------|----------|
| Airflow Web UI | http://localhost:8080 | airflow | airflow |
| MinIO Console | http://localhost:9001 | minioadmin | minioadmin |
| PostgreSQL | localhost:5432 | airflow | airflow |

## Project Structure
```
airflow/
│
├── .env                       # Environment variables
├── docker-compose.yaml         # Docker setup
├── README.md                   # Documentation
│
├── config/                     # Airflow configs
├── dags/                       # ETL DAGs
│   ├── bronze_dag_simple.py
│   ├── silver_layer_dag.py
│   └── gold_dag.py
│
├── logs/                       # Auto-generated Airflow logs
├── minio-data/                 # Data lake (mounted into MinIO)
│   ├── bronze/
│   ├── silver/
│   └── gold/
│
├── plugins/                    # Custom Airflow plugins
└── gold_exports/               # Deliverables for DA team
    ├── gold_dump.sql
    ├── dim_customers.parquet
    ├── dim_sellers.parquet
    ├── dim_products.parquet
    ├── dim_date.parquet
    └── fact_orders.parquet
```

## How It Works

**Bronze Layer (Raw Data)**
- Ingests from Kaggle datasets + DummyJSON API
- Stores raw files into MinIO → /bronze/

**Silver Layer (Cleaned Data)**
- Cleans and validates data using PySpark
- Writes processed data into /silver/

**Gold Layer (Business Tables)**
- Aggregates and joins into star-schema: dim_customers, dim_sellers, dim_products, dim_date, fact_orders
- Writes to /gold/ in MinIO

**Note:** The gold layer does not automatically load tables into PostgreSQL. Users need to perform this step manually if required.

**Verification**
- Confirm in Airflow logs that all tasks completed successfully
- Query PostgreSQL after loading: `SELECT * FROM fact_orders LIMIT 5;`

## PostgreSQL Setup & Manual Loading

PostgreSQL is already provided as part of the `docker-compose.yml` setup and runs automatically when you start the environment.

### Manual Loading Guide

1. Start the Docker environment:
```bash
docker compose up
```

2. Find your PostgreSQL container name:
```bash
docker ps
```

3. Access the PostgreSQL container:
```bash
docker exec -it <postgres_container_name> psql -U airflow -d airflow
```

4. Create the target database (if needed):
```sql
CREATE DATABASE gold_db;
\c gold_db
```

5. Exit PostgreSQL and load the SQL dump from your host machine:
```bash
docker exec -i <postgres_container_name> psql -U airflow -d gold_db < gold_exports/gold_dump.sql
```

6. Verify the tables were loaded:
```bash
docker exec -it <postgres_container_name> psql -U airflow -d gold_db
```
```sql
\dt
SELECT * FROM fact_orders LIMIT 5;
```

7. Done! Your gold tables are now available in PostgreSQL.

## Verification Checklist

| Tool | Check | Command / URL |
|------|-------|---------------|
| Docker | Containers running | `docker ps` |
| Airflow | Web UI active | http://localhost:8080 |
| MinIO | Buckets visible | http://localhost:9001 |
| PostgreSQL | Tables exist | Connect with pgAdmin / Power BI |

## Data Analysis Team Guide

The Gold Layer is finalized and ready for your analysis. You can choose between PostgreSQL or Parquet files to work with the curated data.

### Option A: Connect Power BI to PostgreSQL (Recommended)

You can directly query the five curated tables:

| Table | Description |
|-------|-------------|
| dim_customers | Customer info, reviews, avg spend |
| dim_sellers | Seller profiles and performance |
| dim_products | Product categories and attributes |
| dim_date | Calendar table for time-series |
| fact_orders | Transaction-level data linked to all dimensions |

**Connection Details**

| Parameter | Value |
|-----------|-------|
| Host | localhost |
| Port | 5432 |
| Database | gold_db (or airflow) |
| Username | airflow |
| Password | airflow |

**Steps to Connect:**

1. Load the data into PostgreSQL using the manual loading guide above

2. Open Power BI Desktop

3. Get Data → PostgreSQL Database

4. Enter the connection details above

5. Select the tables you want to import

### Option B: Use Parquet Files Directly

If you prefer not to use PostgreSQL, you can work directly with the Parquet exports:

**Path:** `/gold_exports/`

**Files:**
- dim_customers.parquet
- dim_sellers.parquet
- dim_products.parquet
- dim_date.parquet
- fact_orders.parquet

Load them in Power BI → Get Data → Parquet, or read them in Python / Pandas.

## Final Deliverables

These files were manually exported from the completed Gold Layer after the Airflow DAGs executed successfully:

| File Type | Location | Purpose |
|-----------|----------|---------|
| gold_dump.sql | /gold_exports/ | PostgreSQL dump (all 5 tables) |
| *.parquet files | /gold_exports/ | Equivalent datasets for BI tools |

## Suggested Dashboards

| Dashboard | Example KPIs |
|-----------|--------------|
| Sales Overview | Total Revenue, Avg Order Value, Orders by Category |
| Customer Insights | Repeat Customers, Avg Review Scores |
| Product Analysis | Top Categories, Sales by Price Range |
| Seller Performance | Avg Ratings, Order Fulfillment |
| Delivery Metrics | Avg Delivery Days, Delays, Regional Trends |

## Credits

**Data Engineering Team**
- Muhammad Awais (Infrastructure, Airflow & Gold Layer)
- Afnan Khan (Bronze Layer)
- Farheen Muzaffar (Silver Layer)
- Ghazal E Ashar (Gold Layer Transformations)

**Data Analysis Team**
- Abdur Rehman
- Aqsa Majeed
- Ayesha Saleh
- Salman Qureshi
- Saud Ijaz
- Wania Nafees
- Zohair Raza
```

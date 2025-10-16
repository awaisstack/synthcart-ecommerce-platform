# 🛒 SynthCart E-Commerce Data Engineering Platform

## 📘 Overview
This project simulates a **modern data engineering architecture** for an e-commerce platform — built collaboratively by the Data Engineering (DE) and Data Analysis (DA) teams.

It implements an end-to-end **Medallion Architecture** (Bronze → Silver → Gold) using modern open-source tools.

---

## 🏗️ Architecture Components

| Layer | Tool | Description |
|-------|------|-------------|
| Data Lake | **MinIO** | Stores raw → cleaned → curated data |
| Workflow Orchestration | **Apache Airflow** | Automates ETL pipelines (Bronze, Silver, Gold) |
| Data Warehouse | **PostgreSQL** | Stores final business-ready tables |
| BI Layer | **Power BI** | Used by DA team for analytics dashboards |
| Infrastructure | **Docker Compose** | Containerized setup for easy reproducibility |

---

## ⚙️ Setup Instructions (Windows)

### 🧩 Step 1 — Prerequisites
Before starting, make sure you have:
- 🐳 **Docker Desktop** (running)
- 💻 **VS Code** (optional but recommended)
- 🌐 **Internet Connection**

---

### 🧱 Step 2 — Clone the Repository
Open **PowerShell** and run:

```bash
cd Desktop
git clone https://github.com/awaisstack/synthcart-ecommerce-platform.git
cd synthcart-ecommerce-platform/airflow
```

---

### 🚀 Step 3 — Start the Environment
Make sure Docker Desktop is running, then execute:

```bash
docker compose up
```

This command will:
* Start PostgreSQL, Redis, and Airflow
* Connect to your MinIO storage
* Create all containers automatically

---

### 🌐 Step 4 — Access the Services

| Service | URL | Username | Password |
|---------|-----|----------|----------|
| Airflow Web UI | http://localhost:8080 | `airflow` | `airflow` |
| MinIO Console | http://localhost:9001 | `minioadmin` | `minioadmin` |
| PostgreSQL (via pgAdmin) | `localhost:5432` | `postgres` | your local password |

---

## 🗂️ Project Structure

```
airflow/
│
├── config/                # Airflow configuration files
├── dags/                  # Python DAGs (Bronze, Silver, Gold)
├── logs/                  # Auto-generated Airflow logs
├── minio-data/            # Local data lake storage
│   ├── bronze/
│   ├── silver/
│   └── gold/
├── plugins/               # Custom Airflow plugins (if any)
├── .env                   # Environment variables
└── docker-compose.yaml    # Docker setup file
```

---

## 🧠 How It Works (Conceptually)

1. **Bronze Layer (Raw Data)**
   * Pulls data from Kaggle (CSV) and DummyJSON API
   * Saves raw files into MinIO `bronze/`

2. **Silver Layer (Cleaned Data)**
   * Cleans and validates data using PySpark
   * Writes processed data into MinIO `silver/`

3. **Gold Layer (Business Tables)**
   * Aggregates data and writes final dimension & fact tables
   * Loads them into PostgreSQL (`synthcart_dw`)

4. **Data Analysis (Power BI)**
   * Power BI connects to PostgreSQL and visualizes insights

---

## ✅ Verification Checklist

| Tool | Check | Command / URL |
|------|-------|---------------|
| Docker | Containers running | `docker ps` |
| MinIO | Opens in browser | http://localhost:9001 |
| PostgreSQL | Database exists | Use `pgAdmin` → `synthcart_dw` |
| Airflow | Dashboard active | http://localhost:8080 |
| GitHub | Repo online | Visit your repo URL |

---

## 🤝 Team Collaboration Notes

Each teammate only needs to:
1. Clone this repo
2. Run `docker compose up` inside the `/airflow` folder
3. Access the Airflow and MinIO interfaces

They do NOT need to manually install:
* MinIO
* Airflow
* PostgreSQL

Everything runs automatically inside Docker.

---

## 🧩 Future Tasks

* Add Airflow DAGs for Bronze, Silver, Gold
* Create connection configs for MinIO and PostgreSQL
* Add sample ingestion scripts
* Document transformation logic in `/docs`

---

## 🧾 Credits

**Data Engineering Team:**
* Muhammad Awais (Infrastructure & Setup)
* Afnan Khan (Bronze Layer)
* Farheen Muzaffar (Silver Layer)
* Ghazal E Ashar (Gold Layer)

**Data Analysis Team:**
* Abdur Rehman, Aqsa Majeed, Ayesha Saleh, Salman Qureshi, Saud Ijaz, Wania Nafees, Zohair Raza

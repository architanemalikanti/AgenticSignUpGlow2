#!/usr/bin/env python3
"""
Script to create database tables from SQLAlchemy models.
Run this once to initialize your database schema.
"""
from database.db import engine, Base
from database.models import User

if __name__ == "__main__":
    # Drop all tables (optional - uncomment if you want to reset)
    # Base.metadata.drop_all(bind=engine)
    # print("🗑️  Dropped all existing tables")
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("✅ Tables created successfully!")
    
    # Print table names
    print("\n📋 Created tables:")
    for table in Base.metadata.sorted_tables:
        print(f"   - {table.name}")


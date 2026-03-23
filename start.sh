#!/bin/bash

echo "Создание виртуального окружения..."
python3 -m venv venv

echo "Активация виртуального окружения..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Запуск main.py..."
python3 main.py


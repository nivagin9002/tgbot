FROM python:3.12-slim

WORKDIR /app

# Сначала зависимости — кешируются, если requirements не менялись
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код бота
COPY . .

# Запуск бота
CMD ["python", "bot.py"]

FROM python:3.11-slim

# تثبيت التبعيات اللازمة للنظام
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# إعداد مجلد العمل
WORKDIR /app

# نسخ ملف المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# التأكد من وجود قاعدة البيانات
RUN python3 init_db.py

# تشغيل البوت
CMD ["python", "bot_crashproof.py"]

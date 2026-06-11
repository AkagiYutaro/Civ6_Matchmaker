# 軽量なPython環境を指定
FROM python:3.10-slim

# コンテナ内の作業ディレクトリを作成
WORKDIR /app

# 必要なライブラリをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ソースコード一式をコピー
COPY . .

# BOTを起動
CMD ["python", "main.py"]

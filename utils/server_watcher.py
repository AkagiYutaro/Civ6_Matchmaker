import logging
import os
from flask import Flask, request
from threading import Thread

# ==========================================
# 監視用サーバー (Server Watcher)
# ==========================================
# 目的: Renderの無料枠で15分間アクセスがないとスリープするのを防ぐため、
# UptimeRobot等からのPingを受信し続ける軽量なWebサーバー。

# Flaskのデフォルトのアクセスログ(200 OK等)がコンソールを埋め尽くさないよう、
# WARNING以上のエラー時のみ出力するプロ仕様のログ設定
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

app = Flask('Civ6BotServerWatcher')

@app.route('/')
def home():
    """監視サービスからのPingアクセスを受け付けるエンドポイント"""
    # X-Forwarded-For ヘッダーからプロキシ背後の本当のIPアドレスを取得
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    # 生存確認が取れた行だけログ出力
    print(f"[WATCHER-PING] Access from {client_ip} - Status: ONLINE")
    return "Civ6 Matchmaker Bot is active and running!"

def _run_server():
    """Flaskサーバーの起動プロセス"""
    # Render環境で自動割り当てされるPORT環境変数を取得 (デフォルトは8080)
    port = int(os.environ.get("PORT", 8080))
    try:
        # host='0.0.0.0' により、外部からのアクセスを許可
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        print(f"[CRITICAL ERROR] ServerWatcherの起動に失敗しました: {e}")

def start_server_watcher():
    """
    メインプロセス(Discord BOT)をブロックしないよう、
    バックグラウンドスレッドで監視サーバーを立ち上げる。
    """
    server_thread = Thread(target=_run_server)
    # daemon=True: メインプログラム(BOT)終了時にこのスレッドも道連れで終了させる
    server_thread.daemon = True
    server_thread.start()
    print("[SUCCESS] バックグラウンド監視サーバー (ServerWatcher) が起動しました。")
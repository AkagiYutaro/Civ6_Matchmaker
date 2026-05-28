import os
import discord
from discord.ext import commands
from discord import app_commands
import gspread
from google.oauth2.service_account import Credentials
import itertools
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# [v1.4] スラッシュコマンド同期処理(clear_commands + sync)を実装
# ==========================================
# 1. 設定項目
# ==========================================
load_dotenv()
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
CREDENTIALS_FILE = os.getenv("CREDS_FILE", "credentials.json")

# ==========================================
# ダミーの Web サーバー (Render 維持用)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Civ6 Matchmaker Bot v1.4 is alive!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

t = Thread(target=run_server)
t.start()

# ==========================================
# BOT クラス定義
# ==========================================
class MatchmakerBot(commands.Bot):
    def __init__(self):
        # すべてのインテントを有効化
        super().__init__(command_prefix="!", intents=discord.Intents.all())

    async def setup_hook(self):
        """
        BOT起動時に一度だけ実行される同期処理。
        既存のコマンドを一度クリアし、定義されているコマンドを再登録します。
        """
        try:
            # サーバーのキャッシュをクリアして再同期を実行
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            print("スラッシュコマンドの同期が正常に完了しました。")
        except Exception as e:
            print(f"同期中にエラーが発生しました: {e}")

bot = MatchmakerBot()

# ==========================================
# 2. スプレッドシート連携 (SheetManager)
# ==========================================
class SheetManager:
    def __init__(self, spreadsheet_key, creds_file):
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key)

    # プレイヤーデータの取得など
    def get_player_scores(self, discord_ids):
        # 既存のロジックをここに記述
        pass

# ==========================================
# 7. 起動処理
# ==========================================
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("エラー: DISCORD_BOT_TOKEN が設定されていません。")

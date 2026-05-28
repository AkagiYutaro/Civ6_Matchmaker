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

# [v1.2] スラッシュコマンド同期処理(bot.tree.sync)を追加
# ==========================================
# 1. 設定項目
# ==========================================
load_dotenv()
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
CREDENTIALS_FILE = os.getenv("CREDS_FILE", "credentials.json")

# ==========================================
# ダミーの Web サーバー
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Civ6 Matchmaker Bot v1.2 is alive!"

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
        super().__init__(command_prefix="!", intents=discord.Intents.all())

    async def setup_hook(self):
        # スラッシュコマンドをDiscord側に同期する
        await self.tree.sync()
        print("スラッシュコマンドの同期が完了しました。")

bot = MatchmakerBot()

# ==========================================
# イベントハンドラ
# ==========================================
@bot.event
async def on_ready():
    print(f"{bot.user} としてログインしました。")

# ==========================================
# 2. スプレッドシート連携 (SheetManager)
# ==========================================
class SheetManager:
    # ... (既存のロジックはそのまま維持)
    pass

# ==========================================
# 7. 起動処理
# ==========================================
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    bot.run(token)

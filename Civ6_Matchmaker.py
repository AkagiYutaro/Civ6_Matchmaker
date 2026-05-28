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

# [v1.1] Render無料プラン対応Webサーバー機能追加
# ==========================================
# 1. 設定項目
# ==========================================
load_dotenv()
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY")
CREDENTIALS_FILE = os.getenv("CREDS_FILE", "credentials.json")

MAP_EMOJIS = {
    "七つの海": "🌊",
    "パンゲア": "🗺️",
    "群島": "🏝️",
    "大陸": "🧭"
}

# ==========================================
# ダミーの Web サーバー (Render Web Service維持用)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Civ6 Matchmaker Bot is alive!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# スレッドとしてバックグラウンドで起動
t = Thread(target=run_server)
t.start()

# ==========================================
# 2. スプレッドシート連携 (SheetManager)
# ==========================================
class SheetManager:
    def __init__(self, spreadsheet_key, creds_file):
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key)
        
    def get_player_scores(self, discord_ids):
        players_ws = self.sheet.worksheet("プレイヤーデータ")
        config_ws = self.sheet.worksheet("マスタ設定")
        all_players = players_ws.get_all_records()
        configs = config_ws.get_all_records()
        weight_map = {row["FLG名"]: int(row["現在の配点"]) for row in configs if row.get("FLG名")}
        
        player_scores = {}
        for p_id in discord_ids:
            str_id = str(p_id)
            player_row = next((p for p in all_players if str(p.get("Discord_ID")) == str_id), None)
            if player_row:
                score = sum(int(val) * weight_map.get(col, 0) for col, val in player_row.items() if col in weight_map)
                player_scores[p_id] = {"name": player_row.get("プレイヤー名", f"ID: {str_id}"), "score": score}
            else:
                player_scores[p_id] = None
        return player_scores

    def get_master_flgs(self):
        config_ws = self.sheet.worksheet("マスタ設定")
        return [{"flg_name": row["FLG名"], "score": int(row["現在の配点"]), "description": row.get("備考", "説明なし")} for row in config_ws.get_all_records() if row.get("FLG名")]

    def register_or_update_player(self, discord_id, player_name, active_flgs):
        players_ws = self.sheet.worksheet("プレイヤーデータ")
        headers = players_ws.row_values(1)
        row_data = [str(discord_id) if h == "Discord_ID" else (player_name if h == "プレイヤー名" else (1 if h in active_flgs else 0)) for h in headers]
        all_players = players_ws.get_all_records()
        row_idx = next((idx for idx, p in enumerate(all_players, start=2) if str(p.get("Discord_ID")) == str(discord_id)), None)
        if row_idx:
            players_ws.update(f"A{row_idx}:{gspread.utils.rowcol_to_a1(row_idx, len(row_data))}", [row_data])
        else:
            players_ws.append_row(row_data)
        return True

# ==========================================
# 3. チーム均等化・Discord UIロジック (省略)
# ...既存ロジックをここに継続...
# ==========================================

# ==========================================
# 7. 起動処理
# ==========================================
if __name__ == "__main__":
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
    # ...セットアップ処理...
    token = os.getenv("DISCORD_BOT_TOKEN")
    bot.run(token)

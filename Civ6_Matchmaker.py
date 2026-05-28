import os
import discord
from discord.ext import commands
from discord import app_commands
import gspread
from google.oauth2.service_account import Credentials
import itertools
from dotenv import load_dotenv

# .env ファイルから環境変数を読み込む
load_dotenv()

# ==========================================
# 1. 設定項目
# ==========================================
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY", "あなたのスプレッドシートKEYをここに")
CREDENTIALS_FILE = "credentials.json"

MAP_EMOJIS = {
    "七つの海": "🌊",
    "パンゲア": "🗺️",
    "群島": "🏝️",
    "大陸": "🧭"
}

# ==========================================
# 2. スプレッドシート連携クラス
# ==========================================
class SheetManager:
    def __init__(self, spreadsheet_key, creds_file):
        self.scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
        self.client = gspread.authorize(self.creds)
        self.sheet = self.client.open_by_key(spreadsheet_key)
        
    def get_player_scores(self, discord_ids):
        try:
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
                    score = sum(int(player_row.get(col, 0)) * weight_map.get(col, 0) for col in weight_map)
                    player_scores[p_id] = {"name": player_row.get("プレイヤー名", f"ID: {str_id}"), "score": score}
                else:
                    player_scores[p_id] = None
            return player_scores
        except Exception as e:
            print(f"[ERROR] スプレッドシート読み込み失敗: {e}")
            raise e

    def get_master_flgs(self):
        try:
            config_ws = self.sheet.worksheet("マスタ設定")
            configs = config_ws.get_all_records()
            return [{"flg_name": row["FLG名"], "score": int(row["現在の配点"]), "description": row.get("備考", "説明なし")} for row in configs if row.get("FLG名")]
        except:
            return []

    def register_or_update_player(self, discord_id: int, player_name: str, active_flgs: list):
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            headers = players_ws.row_values(1)
            all_players = players_ws.get_all_records()
            str_id = str(discord_id)
            
            row_data = [str_id if h == "Discord_ID" else (player_name if h == "プレイヤー名" else (1 if h in active_flgs else 0)) for h in headers]
            
            row_idx = next((idx for idx, p in enumerate(all_players, start=2) if str(p.get("Discord_ID")) == str_id), None)
            if row_idx:
                players_ws.update(f"A{row_idx}:{gspread.utils.rowcol_to_a1(row_idx, len(row_data))}", [row_data])
            else:
                players_ws.append_row(row_data)
            return True
        except Exception as e:
            print(f"[ERROR] スプレッドシートへの登録に失敗しました: {e}")
            return False

# ==========================================
# 3. チーム均等化・UIロジック
# ==========================================
def balance_teams(players_info):
    p_ids = list(players_info.keys())
    n = len(p_ids)
    half = n // 2
    best_diff = float("inf")
    best_team_a, best_team_b = [], []
    for team_a_ids in itertools.combinations(p_ids, half):
        team_a_ids = list(team_a_ids)
        team_b_ids = [p for p in p_ids if p not in team_a_ids]
        score_a = sum(players_info[p_id]["score"] for p_id in team_a_ids)
        score_b = sum(players_info[p_id]["score"] for p_id in team_b_ids)
        diff = abs(score_a - score_b)
        if diff < best_diff:
            best_diff, best_team_a, best_team_b = diff, team_a_ids, team_b_ids
    return best_team_a, best_team_b

# [UIクラスは省略しますが、元のコードを維持してください]
# (RegistrationFormView, RegisterChannelView, MatchmakerView クラスをここに配置)

# ==========================================
# 5. BOT基本クラス (同期処理を実装)
# ==========================================
class CivBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)
        self.sheet_manager = SheetManager(SPREADSHEET_KEY, CREDENTIALS_FILE)

    async def setup_hook(self):
        # 【重要】ここで同期処理を実行
        try:
            self.tree.clear_commands(guild=None) # グローバルコマンドをクリア
            await self.tree.sync()               # 再登録
            print("[SUCCESS] スラッシュコマンドが同期されました")
        except Exception as e:
            print(f"[ERROR] 同期中にエラー: {e}")
            
        # 永続Viewのリスナー登録
        # self.add_view(RegisterChannelView(self.sheet_manager))

bot = CivBot()

@bot.event
async def on_ready():
    print(f"[SUCCESS] ログインしました: {bot.user.name}")
    await bot.change_presence(activity=discord.Game(name="Civilization VI"))

# ==========================================
# 6. コマンド定義
# ==========================================
@bot.tree.command(name="civ_match", description="Civ6対戦募集を開始します")
async def civ_match(interaction: discord.Interaction):
    await interaction.response.send_message("募集パネルを作成中...")

@bot.tree.command(name="civ_setup_register", description="【管理者用】登録パネル設置")
async def civ_setup_register(interaction: discord.Interaction):
    await interaction.response.send_message("アンケートパネルを作成中...")

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    bot.run(token)

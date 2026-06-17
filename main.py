import os
import discord
from discord.ext import commands
import logging

# ==========================================
# 1. 環境変数の読み込み
# ==========================================
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# utils/server_watcher.py のインポート
try:
    from utils.server_watcher import start_server_watcher
except ImportError:
    print("[WARNING] utils.server_watcher が見つかりません。")
    def start_server_watcher(): pass

# utils/sheet_manager.py のインポート（追加）
try:
    from utils.sheet_manager import SheetManager
except ImportError:
    print("[WARNING] utils.sheet_manager が見つかりません。")
    SheetManager = None


# ==========================================
# 2. メインBOTクラス定義
# ==========================================
class MatchmakerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        # プロ仕様：print文の代わりに強力なロガーを使用
        self.logger = logging.getLogger('discord')
        
        # 👇 【修正箇所】スプレッドシートマネージャーをBotに持たせる処理を追加
        if SheetManager:
            self.sheet_manager = SheetManager(
                spreadsheet_key=os.getenv("SPREADSHEET_KEY"),
                creds_file="credentials.json"
            )
        else:
            self.sheet_manager = None

    async def setup_hook(self):
        self.logger.info("=== setup_hookを開始します (Cogsの読み込みとコマンド同期) ===")
        
        # 1. 拡張機能のロード
        initial_extensions = ["cogs.matchmaker"]
        for extension in initial_extensions:
            try:
                await self.load_extension(extension)
                self.logger.info(f"[SUCCESS] 拡張機能 '{extension}' を正常にロードしました。")
            except Exception as e:
                # エラーが起きた場所と理由を詳細にログ出力
                self.logger.error(f"[ERROR] 拡張機能 '{extension}' のロードに失敗: {e}", exc_info=True)

        # 2. スラッシュコマンドの同期
        try:
            self.logger.info("[INFO] スラッシュコマンドの同期を開始します...")
            
            # BOT内部で認識中のコマンド数確認
            local_cmds = self.tree.get_commands()
            self.logger.info(f"[DEBUG] BOT内部で認識中のコマンド数: {len(local_cmds)}")

            # 古いコマンドのキャッシュを一度完全にクリア
            # self.tree.clear_commands(guild=None)
            
            # 再登録（同期）の実行
            synced = await self.tree.sync()
            
            self.logger.info(f"[SUCCESS] {len(synced)} 個のコマンドを同期完了しました！")
            for cmd in synced:
                self.logger.info(f" -> 登録完了: /{cmd.name}")
        except Exception as e:
            self.logger.error(f"[CRITICAL ERROR] コマンド同期失敗: {e}", exc_info=True)

    async def on_ready(self):
        self.logger.info("=" * 40)
        self.logger.info(f"[INFO] ログイン完了: {self.user.name} (ID: {self.user.id})")
        self.logger.info(f"[INFO] 稼働サーバー数: {len(self.guilds)}")
        self.logger.info("=" * 40)

# ==========================================
# 3. エントリーポイント (起動処理)
# ==========================================
if __name__ == "__main__":
    # バックグラウンドWebサーバー起動
    start_server_watcher()
    
    # Discord.pyが提供するプロ仕様のロギング設定を有効化
    discord.utils.setup_logging(level=logging.INFO)
    
    bot = MatchmakerBot()
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    
    if TOKEN:
        bot.run(TOKEN, log_handler=None)
    else:
        logging.critical("[CRITICAL ERROR] DISCORD_BOT_TOKEN が環境変数に設定されていません。")
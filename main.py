import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

# プロ仕様：環境変数のセキュアなロード
load_dotenv()

# 常時稼働用の監視サーバー (utils.server_watcher) の安全なインポート
try:
    from utils.server_watcher import start_server_watcher
except ImportError as e:
    print(f"[WARNING] utils.server_watcher のロードに失敗しました。常時起動なしで実行します。")
    print(f"詳細エラー: {e}")
    def start_server_watcher():
        pass

# ==========================================
# Civ6チーム分けBOT - メイン起動クラス (MatchmakerBot)
# ==========================================
class MatchmakerBot(commands.Bot):
    def __init__(self):
        # チーム振り分け、メンバーのロール取得、メッセージリアクションの監視に
        # 必要となるすべてのインテントを明示的に有効化（Pro仕様）
        intents = discord.Intents.all()
        
        super().__init__(
            command_prefix="!",  # スラッシュコマンドメインのためプレフィックスはダミー
            intents=intents,
            help_command=None    # デフォルトのヘルプコマンドを無効化してスラッシュコマンドに特化
        )

    async def setup_hook(self):
        """BOT起動時に一度だけ実行される初期化処理。Cogsの自動ロードとコマンド同期を行います"""
        print("[INFO] 初期化処理を開始します...")

        # 読み込む拡張機能（Cogs）の定義
        # cogs/matchmaker.py、cogs/leaders.py の作成が完了したらコメントアウトを解除します
        initial_extensions = [
            "cogs.matchmaker",
            # "cogs.leaders",
        ]

        # 拡張機能（Cogs）を動的にインポート
        for extension in initial_extensions:
            try:
                await self.load_extension(extension)
                print(f"[SUCCESS] 拡張機能 '{extension}' のロードに成功しました。")
            except Exception as e:
                print(f"[ERROR] 拡張機能 '{extension}' のロードに失敗しました:\n  -> {e}")

        # スラッシュコマンドをDiscordサーバーに同期する
        try:
            # 既存のグローバルキャッシュをリセットして同期
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            print("[SUCCESS] スラッシュコマンドのグローバル同期が完了しました。")
        except discord.errors.Forbidden:
            print("[ERROR] スラッシュコマンドの同期に失敗しました: 'applications.commands' 権限がBOTに付与されているか確認してください。")
        except Exception as e:
            print(f"[ERROR] コマンド同期中に予期せぬエラーが発生しました: {e}")

    async def on_ready(self):
        """BOTがDiscordのGatewayとの接続を完了した際に呼ばれるイベント"""
        print("==========================================")
        print(f"[INFO] ログイン完了: {self.user.name} (ID: {self.user.id})")
        print(f"[INFO] 接続中のサーバー数: {len(self.guilds)}")
        print("[INFO] BOTは現在オンラインになり、正常に稼働しています。")
        print("==========================================")

# ==========================================
# エントリーポイント（プログラム実行開始位置）
# ==========================================
if __name__ == "__main__":
    # 1. Renderのスリープを防止するバックグラウンド監視サーバー（Server Watcher）を起動
    start_server_watcher()

    # 2. BOTインスタンスの作成
    bot = MatchmakerBot()

    # 3. トークンを環境変数（または.env）からセキュアに取得してBOTを起動
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")

    if not TOKEN:
        print("[CRITICAL ERROR] Discordトークン (DISCORD_BOT_TOKEN) が環境変数に設定されていません。")
        print(".env ファイルまたはホスティング環境（Render等）の設定を再確認してください。")
    else:
        try:
            bot.run(TOKEN)
        except discord.errors.LoginFailure:
            print("[CRITICAL ERROR] Discordへのログインに失敗しました。トークンが正しいか確認してください。")
        except Exception as e:
            print(f"[CRITICAL ERROR] BOTの起動中に予期せぬ障害が発生しました: {e}")
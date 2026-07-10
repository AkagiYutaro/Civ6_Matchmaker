import discord
from discord.ext import commands
from discord import app_commands

# 先ほど作成した ui フォルダのファイルから部品を読み込む
from ui.matchmaker_ui import MatchmakerView, MAP_EMOJIS

class MatchmakerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="civ_match", description="Civ6マルチプレイの参加登録とチーム分けを開始します。")
    async def civ_match(self, interaction: discord.Interaction):
        host = interaction.user
        
        # メンションしたいロールID
        ROLE_ID = 123456789012345678 # 実際のロールID
        mention_str = f"<@&{ROLE_ID}>"
        
        # 募集用メッセージの作成
        embed = discord.Embed(
            title="🌐 Civ6 Matchmaking",
            description=f"{mention_str}\n<@{host.id}> が募集を開始しました。",
            color=discord.Color.blurple()
        )
        
        # UI側で更新するために、初期状態のフィールド（インデックス0）を追加しておく必要があります
        embed.add_field(name=f"参加者一覧 (1名)", value=f"・<@{host.id}>", inline=False)
        
        # ui/matchmaker_ui.py で定義した View をここで呼び出す！
        view = MatchmakerView(host=host, sheet_manager=self.bot.sheet_manager)
        
        # メッセージを送信して終了（これ1回だけにする！）
        await interaction.response.send_message(content=f"{mention_str}", embed=embed, view=view)

# この関数があることで、main.py がこのファイルを拡張機能として認識してくれます
async def setup(bot):
    await bot.add_cog(MatchmakerCog(bot))
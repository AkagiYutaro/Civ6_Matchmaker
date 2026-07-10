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
        
        view = MatchmakerView(host=host, sheet_manager=self.bot.sheet_manager)
        
        # メッセージを送信して終了（これ以降にあった古いリアクション追加処理は全て削除）
        await interaction.response.send_message(embed=embed, view=view)
        # メンションをEmbedの外側に送信してから、Embedを送信する
        await interaction.response.send_message(content=f"{mention_str}", embed=embed, view=view)
        
        # ui/matchmaker_ui.py で定義した View をここで呼び出す！
        view = MatchmakerView(host=host, sheet_manager=self.bot.sheet_manager)
        
        await interaction.response.send_message(embed=embed, view=view)
        
        # 送信したメッセージオブジェクトを取得
        sent_msg = await interaction.original_response()
        
        # 投票用絵文字を自動リアクション追加
        for emoji in MAP_EMOJIS.values():
            try:
                await sent_msg.add_reaction(emoji)
            except Exception as e:
                print(f"[WARNING] リアクションの追加に失敗: {emoji} ({e})")

# この関数があることで、main.py がこのファイルを拡張機能として認識してくれます
async def setup(bot):
    await bot.add_cog(MatchmakerCog(bot))
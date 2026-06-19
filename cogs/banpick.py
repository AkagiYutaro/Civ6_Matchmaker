import discord
from discord import app_commands
from discord.ext import commands

class BanPickSelect(discord.ui.Select):
    def __init__(self, rules: list, parent_view):
        self.parent_view = parent_view
        options = []
        for r in rules:
            desc = r.get("説明（備考）", "")
            if len(desc) > 50:
                desc = desc[:47] + "..."
            
            emoji = r.get("絵文字", "").strip()
            if not emoji:
                emoji = None
                
            options.append(discord.SelectOption(
                label=r.get("ルール名", "名称未設定"),
                emoji=emoji,
                description=desc,
                value=r.get("ルール名", "名称未設定")
            ))
            
        super().__init__(
            placeholder="⚔️ BAN/PICKのルールを選択してください...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="civ_banpick_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # 選択されたルールを一時保存し、確定ボタンを有効化
        self.parent_view.selected_rule = self.values[0]
        self.parent_view.confirm_button.disabled = False
        await interaction.response.edit_message(view=self.parent_view)


class BanPickConfirmButton(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(
            label="決定", 
            style=discord.ButtonStyle.success, 
            disabled=True, 
            custom_id="civ_banpick_confirm"
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        rule_name = self.parent_view.selected_rule
        
        # 二重押し防止のためUIを無効化
        for child in self.parent_view.children:
            child.disabled = True
        await interaction.response.edit_message(view=self.parent_view)
        
        # 確定したルールを全員にアナウンス
        await interaction.followup.send(f"🎉 **BANPICK：{rule_name}**")


class BanPickView(discord.ui.View):
    """チーム分け機能(Matchmaker)から呼び出される専用View"""
    def __init__(self, host: discord.Member, rules: list):
        super().__init__(timeout=None)
        self.host = host
        self.selected_rule = None
        
        self.confirm_button = BanPickConfirmButton(self)
        self.add_item(BanPickSelect(rules, self))
        self.add_item(self.confirm_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ホスト以外が触ろうとしたらブロック
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("ホストのみがBAN/PICKルールを決定できます。", ephemeral=True)
            return False
        return True

# ==========================================
# 単独呼び出し用コマンド (後からルールを変えたい時用)
# ==========================================
class BanPickCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="civ_banpick", description="BAN/PICKルールの選択パネルを単独で呼び出します。")
    async def civ_banpick(self, interaction: discord.Interaction):
        host = interaction.user
        
        rules = []
        if hasattr(self.bot.sheet_manager, "get_banpick_rules"):
            rules = self.bot.sheet_manager.get_banpick_rules()
            
        if not rules:
            rules = [
                {"ルール名": "完全ランダム", "絵文字": "🎲", "説明（備考）": "全員がランダムな指導者でプレイします。"},
                {"ルール名": "1Ban 3Pick", "絵文字": "🚫", "説明（備考）": "各チーム1つの文明をBANし、3つの文明から1つを選びます。"}
            ]
            
        view = BanPickView(host=host, rules=rules)
        await interaction.response.send_message(
            f"ホスト <@{host.id}> は、BAN/PICKのルールを決定してください。", 
            view=view
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(BanPickCog(bot))
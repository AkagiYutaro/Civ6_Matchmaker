import discord
from discord import app_commands
from discord.ext import commands
import itertools
import os

# ==========================================
# 1. 定数・設定
# ==========================================
# 万が一シートから取得できなかった場合の安全装置
DEFAULT_MAP_EMOJIS = {
    "パンゲア": "🌍",
    "大陸": "🗺️",
    "フラクタル": "🌀",
    "七つの海": "🌊",
    "シャッフル": "🎲"
}

# ==========================================
# 2. ロジック・アルゴリズム
# ==========================================
def balance_teams(players_info):
    """
    参加プレイヤーを2チームに分け、チームの合計スコア差が最小になる組み合わせ（全探索）を返す。
    """
    p_ids = list(players_info.keys())
    n = len(p_ids)
    half = n // 2
    
    best_diff = float("inf")
    best_team_a = []
    best_team_b = []
    
    # 全組み合わせの列挙 (N/2 人を選ぶ)
    for team_a_ids in itertools.combinations(p_ids, half):
        team_a_ids = list(team_a_ids)
        team_b_ids = [p for p in p_ids if p not in team_a_ids]
        
        score_a = sum(players_info[p_id]["score"] for p_id in team_a_ids)
        score_b = sum(players_info[p_id]["score"] for p_id in team_b_ids)
        
        diff = abs(score_a - score_b)
        
        if diff < best_diff:
            best_diff = diff
            best_team_a = team_a_ids
            best_team_b = team_b_ids
            
    return best_team_a, best_team_b

# ==========================================
# 3. Discord UIコンポーネント (募集パネル系)
# ==========================================
class RemovePlayerSelect(discord.ui.Select):
    def __init__(self, parent_view, original_message):
        options = []
        for p_id, p_name in parent_view.participants.items():
            options.append(discord.SelectOption(label=p_name, value=str(p_id)))
        
        if not options:
            options.append(discord.SelectOption(label="参加者がいません", value="none"))

        super().__init__(placeholder="辞退させるプレイヤーを選択", options=options, min_values=1, max_values=1)
        self.parent_view = parent_view
        self.original_message = original_message

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("対象がいません。", ephemeral=True)
            return

        p_id = int(self.values[0])
        if p_id in self.parent_view.participants:
            removed_name = self.parent_view.participants.pop(p_id)
            await self.parent_view.update_embed(original_message=self.original_message)
            await interaction.response.send_message(f"✅ {removed_name} を今回の参加者リストから除外しました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に除外されています。", ephemeral=True)

class RemovePlayerView(discord.ui.View):
    def __init__(self, parent_view, original_message):
        super().__init__(timeout=120)
        self.add_item(RemovePlayerSelect(parent_view, original_message))

class MatchmakerView(discord.ui.View):
    def __init__(self, host: discord.Member, sheet_manager, map_emojis: dict):
        super().__init__(timeout=None)
        self.host = host
        self.sheet_manager = sheet_manager
        self.map_emojis = map_emojis
        self.participants = {host.id: host.display_name}

    async def update_embed(self, interaction: discord.Interaction = None, original_message: discord.Message = None):
        if interaction:
            embed = interaction.message.embeds[0]
        elif original_message:
            embed = original_message.embeds[0]
        else:
            return
            
        member_list_str = "\n".join([f"・<@{p_id}>" for p_id in self.participants.keys()]) if self.participants else "現在参加者なし"
        embed.set_field_at(0, name=f"参加者一覧 ({len(self.participants)}名)", value=member_list_str, inline=False)
        
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif original_message:
            await original_message.edit(embed=embed, view=self)

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success, custom_id="civ_join_btn", row=0)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        await interaction.response.defer(ephemeral=True)
        
        try:
            players_info = self.sheet_manager.get_player_scores([user.id])
            if players_info.get(user.id) is None:
                await interaction.followup.send(
                    "⚠️ **チームの戦力バランスを計算するため、事前にアンケートへの回答が必要です。**\n"
                    "管理者が設置したパネルからアンケートに答えてから、再度参加ボタンを押してください！",
                    ephemeral=True
                )
                return

            if user.id not in self.participants:
                self.participants[user.id] = user.display_name
                await self.update_embed(original_message=interaction.message)
                await interaction.followup.send("✅ 参加登録しました！", ephemeral=True)
            else:
                await interaction.followup.send("既に登録されています！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ データベースの確認中にエラーが発生しました: {e}", ephemeral=True)

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.danger, custom_id="civ_leave_btn", row=0)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in self.participants:
            del self.participants[user.id]
            await self.update_embed(interaction=interaction)
        else:
            await interaction.response.send_message("まだ参加していません！", ephemeral=True)

    @discord.ui.button(label="不在者を外す", style=discord.ButtonStyle.secondary, custom_id="civ_remove_absent_btn", row=1)
    async def remove_absent_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集ホストのみ押すことができます。", ephemeral=True)
            return
            
        if not self.participants:
            await interaction.response.send_message("参加者が誰もいません。", ephemeral=True)
            return

        remove_view = RemovePlayerView(parent_view=self, original_message=interaction.message)
        await interaction.response.send_message("参加者リストから除外するプレイヤーを選択してください:", view=remove_view, ephemeral=True)

    @discord.ui.button(label="チーム分け（募集者のみ）", style=discord.ButtonStyle.primary, custom_id="civ_calc_btn", row=2)
    async def calc_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集ホストのみ押すことができます。", ephemeral=True)
            return

        if len(self.participants) < 2:
            await interaction.response.send_message("チームを分けるには最低2人のプレイヤーが必要です！", ephemeral=True)
            return

        await interaction.response.defer()

        # マップ投票の集計
        original_msg = interaction.message
        channel = interaction.channel
        msg_with_reactions = await channel.fetch_message(original_msg.id)
        
        map_votes = {}
        for name, emoji in self.map_emojis.items():
            reaction = discord.utils.get(msg_with_reactions.reactions, emoji=emoji)
            if reaction:
                map_votes[name] = reaction.count - 1 # BOT自身の分を引く
            else:
                map_votes[name] = 0

        if map_votes and max(map_votes.values()) > 0:
            max_vote_val = max(map_votes.values())
            voted_maps = [k for k, v in map_votes.items() if v == max_vote_val]
            chosen_map = voted_maps[0]
            map_result_str = f"🗺️ 本日の戦場: **{chosen_map}** （{max_vote_val}票獲得）"
        else:
            map_result_str = f"🗺️ 本日の戦場: **未投票（ランダム等）**"

        # チーム分け実行
        players_info = self.sheet_manager.get_player_scores(list(self.participants.keys()))
        for p_id, p_data in list(players_info.items()):
            if p_data is None:
                players_info[p_id] = {"name": f"未登録({str(p_id)[:5]})", "score": 3}

        team_a, team_b = balance_teams(players_info)
        score_a = sum(players_info[p_id]["score"] for p_id in team_a)
        score_b = sum(players_info[p_id]["score"] for p_id in team_b)

        team_a_str = "\n".join([f"・<@{p_id}> (スコア:{players_info[p_id]['score']})" for p_id in team_a]) or "なし"
        team_b_str = "\n".join([f"・<@{p_id}> (スコア:{players_info[p_id]['score']})" for p_id in team_b]) or "なし"

        result_embed = discord.Embed(
            title="🎮 Civ6 チーム分け結果発表！",
            color=discord.Color.gold()
        )
        result_embed.add_field(name="【対戦設定】", value=map_result_str, inline=False)
        result_embed.add_field(name=f"🔵 チームA (合計スコア: {score_a})", value=team_a_str, inline=True)
        result_embed.add_field(name=f"🔴 チームB (合計スコア: {score_b})", value=team_b_str, inline=True)
        result_embed.set_footer(text="楽しい対戦になりますように！GLHF!")

        for child in self.children:
            child.disabled = True
        await interaction.followup.edit_message(message_id=original_msg.id, view=self)
        await interaction.followup.send(content=f"ホスト <@{self.host.id}> がチームを確定しました！", embed=result_embed)

    @discord.ui.button(label="募集をキャンセル", style=discord.ButtonStyle.danger, custom_id="civ_cancel_btn", row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集ホストのみ押すことができます。", ephemeral=True)
            return
            
        await interaction.response.send_message(f"⚠️ ホスト <@{self.host.id}> が今回の募集をキャンセルしました。")
        await interaction.message.delete()


# ==========================================
# 4. Discord UIコンポーネント (アンケート系)
# ==========================================
class SkillDropdown(discord.ui.Select):
    def __init__(self, flg_list: list):
        max_vals = len(flg_list) if len(flg_list) > 0 else 1
        options = []
        for item in flg_list:
            short_desc = str(item.get("備考", ""))
            if len(short_desc) > 50:
                short_desc = short_desc[:47] + "..."
            
            label_text = str(item.get("FLG名", "")).replace('FLG_', '')
            score = item.get("現在の配点", 0)
            
            options.append(discord.SelectOption(
                label=label_text,
                value=str(item.get("FLG名", "")),
                description=f"配点: {score}点 | {short_desc}"
            ))

        if not options:
            options.append(discord.SelectOption(label="設定されたFLGがありません", value="none"))

        super().__init__(
            placeholder="自分ができる能力にチェックを入れてください（複数選択可）",
            min_values=0,
            max_values=max_vals,
            options=options,
            custom_id="civ_skill_select"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

class RegistrationFormView(discord.ui.View):
    def __init__(self, sheet_manager, flg_list: list):
        super().__init__(timeout=180)
        self.sheet_manager = sheet_manager
        self.flg_list = flg_list
        self.dropdown = SkillDropdown(flg_list)
        self.add_item(self.dropdown)

    @discord.ui.button(label="この内容でスキルを登録する", style=discord.ButtonStyle.success, row=1)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected_flgs = self.dropdown.values
        if "none" in selected_flgs:
            selected_flgs = []
            
        button.disabled = True
        await interaction.response.edit_message(view=self)
        
        player_name = interaction.user.display_name
        try:
            self.sheet_manager.register_or_update_player(
                discord_id=interaction.user.id,
                player_name=player_name,
                active_flgs=selected_flgs
            )
            success = True
        except Exception as e:
            print(f"[ERROR] スキル登録失敗: {e}")
            success = False

        if success:
            total_score = sum(int(item.get("score", 0)) for item in self.flg_list if item.get("flg_name") in selected_flgs)
            selected_names = [f"・{f.replace('FLG_', '')}" for f in selected_flgs]
            selected_str = "\n".join(selected_names) if selected_names else "・なし（初期スコア）"

            embed = discord.Embed(
                title="✅ スキル登録が完了しました！",
                description="情報がスプレッドシートに連携されました。\nこれでチーム分けにいつでも参加できます！",
                color=discord.Color.green()
            )
            embed.add_field(name="登録プレイヤー名", value=player_name, inline=True)
            embed.add_field(name="算出された暫定スコア", value=f"**{total_score} 点**", inline=True)
            embed.add_field(name="申告した能力", value=selected_str, inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("❌ 保存中にエラーが発生しました。時間を置いてやり直してください。", ephemeral=True)

class RegisterChannelView(discord.ui.View):
    def __init__(self, sheet_manager):
        super().__init__(timeout=None)
        self.sheet_manager = sheet_manager

    @discord.ui.button(label="アンケートに回答する", style=discord.ButtonStyle.primary, custom_id="civ_start_register_btn")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            players_info = self.sheet_manager.get_player_scores([interaction.user.id])
        except Exception as e:
            await interaction.followup.send(f"❌ **スプレッドシート読み込みエラー:**\n{e}", ephemeral=True)
            return

        if players_info.get(interaction.user.id) is not None:
            await interaction.followup.send(
                "⚠️ **あなたはすでに登録されています。**\n追加回答や内容の上書き修正を行いたい場合は、管理者に直接お伝えください。", 
                ephemeral=True
            )
            return
        
        flg_list = self.sheet_manager.get_master_flgs()
        if not flg_list:
            await interaction.followup.send("⚠️ スプレッドシートからマスタ設定の取得に失敗しました。", ephemeral=True)
            return

        view = RegistrationFormView(self.sheet_manager, flg_list)
        await interaction.followup.send(
            "📋 **【Civ6 プレイヤー登録】**\n"
            "「達成可能」「得意である」と言える項目をすべて選択し、下の「登録する」ボタンを押してください。",
            view=view,
            ephemeral=True
        )


# ==========================================
# 5. Cog (拡張機能) クラス定義
# ==========================================
class MatchmakerCog(commands.Cog):
    """チーム分け機能と登録機能を提供するCog"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ==========================================
    # 6. スラッシュコマンド
    # ==========================================

    # ==========================================
    # 6.1. (/civ_match) ロールメンション指定オプション付き
    # ==========================================
    @app_commands.command(name="civ_match", description="Civ6マルチプレイの参加登録とマップ投票、チーム分けを開始します。")
    @app_commands.describe(role="募集時にメンションを送信したいロールを指定します (省略時はメンションなし)")
    async def civ_match(self, interaction: discord.Interaction, role: discord.Role = None):
        host = interaction.user

        # メンション文字列の作成 (ロールが指定されていればメンションし、ない場合は空文字)
        if role:
            mention_str = f"{role.mention}\n\n"
        else:
            mention_str = ""

        # MAP_EMOJISの動的取得（失敗時はデフォルトを使用）
        try:
            if hasattr(self.bot.sheet_manager, "get_map_emojis"):
                map_emojis = self.bot.sheet_manager.get_map_emojis()
                if not map_emojis:
                    map_emojis = DEFAULT_MAP_EMOJIS
            else:
                map_emojis = DEFAULT_MAP_EMOJIS
        except Exception:
            map_emojis = DEFAULT_MAP_EMOJIS

        embed = discord.Embed(
            title="⚔️ Civ6 マルチプレイ対戦募集！ ⚔️",
            description=f"ホスト <@{host.id}> が募集を開始しました！\n"
                        "以下のボタンから「参加」または「辞退」を表明してください。\n"
                        "マップスタンプ（リアクション）に投票をお願いします。",
            color=discord.Color.blue()
        )
        embed.add_field(name="参加者一覧", value=f"・<@{host.id}>", inline=False)
        
        vote_guide = "\n".join([f"{emoji} : **{name}**" for name, emoji in map_emojis.items()])
        embed.add_field(name="【マップ投票】", value=vote_guide, inline=False)
        
        view = MatchmakerView(host=host, sheet_manager=self.bot.sheet_manager, map_emojis=map_emojis)
        
        # メッセージ送信（ロールが指定されている場合のみ、本文にメンションを付けます）
        await interaction.response.send_message(content=mention_str if mention_str else None, embed=embed, view=view)

        sent_msg = await interaction.original_response()
        
        for emoji in map_emojis.values():
            try:
                await sent_msg.add_reaction(emoji)
            except Exception:
                pass

    # ==========================================
    # 6.2. 管理者用：スキルアンケート常設コマンド (/civ_setup_register)
    # ==========================================
    @app_commands.command(name="civ_setup_register", description="【管理者専用】プレイヤー用の登録パネルを設置します。")
    @app_commands.default_permissions(administrator=True)
    async def civ_setup_register(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚔️ Civ6 プレイヤー登録 ⚔️",
            description="Civ6マルチサーバーへようこそ！\n"
                        "プレイヤー全員にスキル登録をお願いしています。\n\n"
                        "以下のボタンからアンケートに回答して登録を済ませてください！\n"
                        "※未登録のプレイヤーは、募集時の「参加ボタン」が押せなくなります。",
            color=discord.Color.dark_purple()
        )
        embed.add_field(
            name="📝 登録・更新方法",
            value="1. 下の「アンケートに回答する」ボタンを押す。\n"
                  "2. 自分専用のドロップダウンから達成可能な能力項目を選択（複数可）。\n"
                  "3. 送信ボタンを押して「登録完了」と表示されればOKです！",
            inline=False
        )

        view = RegisterChannelView(self.bot.sheet_manager)
        await interaction.response.send_message(embed=embed, view=view)

# ==========================================
# 6. Cogのセットアップ関数
# ==========================================
async def setup(bot: commands.Bot):
    # Cog を BOT に登録
    await bot.add_cog(MatchmakerCog(bot))
    # BOT再起動後もアンケート登録パネル(ボタン)が反応するようにリスナーを登録
    bot.add_view(RegisterChannelView(bot.sheet_manager))

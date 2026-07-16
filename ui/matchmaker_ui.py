import discord
import random
from logic.matchmaker_logic import balance_teams, calculate_map_votes
from ui.map_voting_ui import MapVotingView

MAP_EMOJIS = {
    "七つの海": "7️⃣",
    "パンゲア": "🇵",
    "パンゲアウルティマ": "🇺",
    "湖": "🇱",
    "ハイランド": "🐴",
    "豊かな台地": "🌳",
    "群島": "🏝️",
    "地軸傾斜": "🏹"
}

# ==========================================
# 1. 全員に見える公開用パネル (参加・辞退・マップ投票)
# ==========================================
class MatchmakerPublicView(discord.ui.View):
    def __init__(self, host, sheet_manager):
        super().__init__(timeout=None)
        self.host = host
        self.sheet_manager = sheet_manager
        self.participants = {host.id: host.display_name}
        self.map_votes_data = {} # 誰が何に投票したかを保持
        
        # チーム分け後に結果を保持するための変数
        self.team_a_str_list = []
        self.team_b_str_list = []
        self.score_a = 0
        self.score_b = 0
        
    async def update_embed(self, interaction: discord.Interaction):
        embed = interaction.message.embeds[0]
        member_list_str = "\n".join([f"・<@{p_id}>" for p_id in self.participants.keys()]) if self.participants else "現在参加者なし"
        embed.set_field_at(0, name=f"参加者一覧 ({len(self.participants)}名)", value=member_list_str, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加", style=discord.ButtonStyle.success, custom_id="civ_join_btn")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        try:
            players_info = self.sheet_manager.get_player_scores([user.id])
        except Exception as e:
            await interaction.response.send_message(f"❌ **スプレッドシート接続エラー** ({e})", ephemeral=True)
            return

        if players_info[user.id] is None:
            await interaction.response.send_message("⚠️ **チーム分けのため事前にアンケートへの回答が必要です。**", ephemeral=True)
            return

        if user.id not in self.participants:
            self.participants[user.id] = user.display_name
            await self.update_embed(interaction=interaction)
            await interaction.followup.send("✅ 参加登録しました！", ephemeral=True)
        else:
            await interaction.response.send_message("既に参加登録済みです！", ephemeral=True)

    @discord.ui.button(label="辞退", style=discord.ButtonStyle.danger, custom_id="civ_leave_btn")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id in self.participants:
            del self.participants[user.id]
            # 辞退したら投票データも消す
            if user.id in self.map_votes_data:
                del self.map_votes_data[user.id]
            await self.update_embed(interaction=interaction)
            await interaction.followup.send("✅ 参加を辞退しました。", ephemeral=True)
        else:
            await interaction.response.send_message("まだ参加登録していません！", ephemeral=True)

    @discord.ui.button(label="🗺️ マップ投票", style=discord.ButtonStyle.secondary, custom_id="civ_vote_map_btn")
    async def vote_map_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.participants:
            return await interaction.response.send_message("⚠️ 先に「参加」ボタンを押してから投票してください。", ephemeral=True)
            
        vote_view = MapVotingView(MAP_EMOJIS, self)
        await interaction.response.send_message(
            content="> 🗺️ プレイしたいマップをリストから選択してください...", 
            view=vote_view, 
            ephemeral=True
        )

# ==========================================
# 不在者削除用のセレクトUI (ホスト専用)
# ==========================================
class RemovePlayerSelect(discord.ui.Select):
    def __init__(self, public_view, original_message):
        options = [discord.SelectOption(label=p_name, value=str(p_id)) for p_id, p_name in public_view.participants.items()]
        if not options:
            options.append(discord.SelectOption(label="参加者がいません", value="none"))
        super().__init__(placeholder="辞退させるプレイヤーを選択", options=options, min_values=1, max_values=1)
        self.public_view = public_view
        self.original_message = original_message

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("対象がいません。", ephemeral=True)
            
        p_id = int(self.values[0])
        if p_id in self.public_view.participants:
            removed_name = self.public_view.participants.pop(p_id)
            if p_id in self.public_view.map_votes_data:
                del self.public_view.map_votes_data[p_id]
            
            embed = self.original_message.embeds[0]
            member_list_str = "\n".join([f"・<@{i}>" for i in self.public_view.participants.keys()]) if self.public_view.participants else "現在参加者なし"
            embed.set_field_at(0, name=f"参加者一覧 ({len(self.public_view.participants)}名)", value=member_list_str, inline=False)
            await self.original_message.edit(embed=embed)
            await interaction.response.send_message(f"✅ {removed_name} を除外しました。", ephemeral=True)
        else:
            await interaction.response.send_message("既に除外されています。", ephemeral=True)

class RemovePlayerView(discord.ui.View):
    def __init__(self, public_view, original_message):
        super().__init__(timeout=120)
        self.add_item(RemovePlayerSelect(public_view, original_message))

# ==========================================
# 2. ホスト専用 操作パネル (チーム分け実行)
# ==========================================
class HostControlView(discord.ui.View):
    def __init__(self, public_message, public_view, host, sheet_manager):
        super().__init__(timeout=None)
        self.public_message = public_message
        self.public_view = public_view
        self.host = host
        self.sheet_manager = sheet_manager

    def is_authorized(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.host.id or interaction.user.guild_permissions.administrator

    @discord.ui.button(label="チーム分け実行", style=discord.ButtonStyle.primary, custom_id="civ_split_teams_btn", row=0)
    async def split_teams_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
            
        participants = self.public_view.participants
        if len(participants) < 2:
            return await interaction.response.send_message("チーム分けには最低2人必要です。", ephemeral=True)

        await interaction.response.defer()

        # 🗺️ 参加者全員のマップ投票を集計
        chosen_map, max_vote_val = calculate_map_votes(self.public_view.map_votes_data, participants, MAP_EMOJIS)
        if max_vote_val > 0:
            map_result_str = f"🗺️ Map: **{chosen_map}** （{max_vote_val}票獲得）"
        else:
            map_result_str = f"🗺️ Map: **{chosen_map}**"

        # ⚖️ スコア取得と均等化ロジック
        players_info = self.sheet_manager.get_player_scores(list(participants.keys()))
        for p_id, p_data in list(players_info.items()):
            if p_data is None:
                players_info[p_id] = {"name": f"未登録({str(p_id)[:5]})", "score": 3}

        team_a, team_b = balance_teams(players_info)
        
        self.public_view.score_a = sum(players_info[p_id]["score"] for p_id in team_a)
        self.public_view.score_b = sum(players_info[p_id]["score"] for p_id in team_b)
        self.public_view.team_a_str_list = [f"・<@{p_id}> ({players_info[p_id]['score']})" for p_id in team_a]
        self.public_view.team_b_str_list = [f"・<@{p_id}> ({players_info[p_id]['score']})" for p_id in team_b]

        # 公開パネルを「チーム分け結果」に書き換え、参加・辞退・投票ボタンを消去する
        embed = discord.Embed(title="チーム分け結果", color=discord.Color.gold())
        embed.add_field(name="【対戦設定】", value=map_result_str, inline=False)
        embed.add_field(name=f"🔵 チームA (計: {self.public_view.score_a})", value="\n".join(self.public_view.team_a_str_list), inline=True)
        embed.add_field(name=f"🔴 チームB (計: {self.public_view.score_b})", value="\n".join(self.public_view.team_b_str_list), inline=True)

        try:
            await self.public_message.edit(embed=embed, view=None)
        except Exception:
            pass

        # 全ての処理が完了したのでホスト操作パネルも消去する
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            content="✅ **チーム分けとマップの集計が完了しました！**",
            view=None
        )

    @discord.ui.button(label="不在者を外す", style=discord.ButtonStyle.secondary, custom_id="civ_remove_absent_btn", row=1)
    async def remove_absent_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
        if not self.public_view.participants:
            return await interaction.response.send_message("参加者がいません。", ephemeral=True)
            
        remove_view = RemovePlayerView(public_view=self.public_view, original_message=self.public_message)
        await interaction.response.send_message("除外するプレイヤーを選択してください:", view=remove_view, ephemeral=True)

    @discord.ui.button(label="募集をキャンセル", style=discord.ButtonStyle.danger, custom_id="civ_cancel_btn", row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_authorized(interaction):
            return await interaction.response.send_message("権限がありません。", ephemeral=True)
        
        await self.public_message.delete()
        await interaction.response.edit_message(content="⚠️ 募集をキャンセルしました。", view=None)
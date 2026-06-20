import discord
from discord import app_commands
from discord.ext import commands
import itertools
import random
import os
import datetime

from cogs.map_voting import MapVoteView

# ==========================================
# 1. 定数・設定
# ==========================================

DEFAULT_MAP_EMOJIS = {
    "パンゲア": "🌍",
    "大陸": "🗺️",
    "フラクタル": "🌀",
    "七つの海": "🌊",
    "シャッフル": "🎲"
}
MAX_MAIN_PLAYERS = 12  # 本参加者の上限人数

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
            if p_id in self.parent_view.map_votes:
                del self.parent_view.map_votes[p_id]
            
            await self.parent_view.update_embed(original_message=self.original_message)
            await interaction.response.send_message(f"✅ {removed_name} をリストから除外しました。補欠がいる場合は自動で繰り上がります。", ephemeral=True)
        else:
            await interaction.response.send_message("既に除外されています。", ephemeral=True)

class RemovePlayerView(discord.ui.View):
    def __init__(self, parent_view, original_message):
        super().__init__(timeout=120)
        self.add_item(RemovePlayerSelect(parent_view, original_message))

# ------------------------------------------
# BAN/PICK ルール決定用コンポーネント
# ------------------------------------------

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
            label="これで決定", 
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
        
        # 選択されたルールに応じた処理の分岐
        if "ドラフト" in rule_name or "グローバルBAN" in rule_name:
            # 今回作成したドラフト機能を呼び出す
            from cogs.banpick import BanPickStartView
            bp_start_view = BanPickStartView(
                host=self.parent_view.host,
                team_a=self.parent_view.team_a,
                team_b=self.parent_view.team_b,
                sheet_manager=self.parent_view.sheet_manager
            )
            await interaction.followup.send(
                content=f"🎉 **BANPICK：{rule_name}**\n"
                        f"ホスト <@{self.parent_view.host.id}> は、待機場に全員が揃ったら下のボタンを押してBAN/PICKを開始してください。\n"
                        f"*(※自動的にチームVCへ移動します)*", 
                view=bp_start_view
            )
        else:
            # まだ実装されていない他のモードの場合
            await interaction.followup.send(
                content=f"🎉 **BANPICKモード：{rule_name}** が選択されました！\n"
                        f"*(※このルールの自動UIは準備中です。口頭または手動で進行してください)*"
            )

class BanPickView(discord.ui.View):
    def __init__(self, host: discord.Member, rules: list, team_a: list, team_b: list, sheet_manager):
        super().__init__(timeout=None)
        self.host = host
        self.team_a = team_a
        self.team_b = team_b
        self.sheet_manager = sheet_manager
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


# ------------------------------------------
# メインの募集・チーム分け用コンポーネント
# ------------------------------------------

class MatchmakerView(discord.ui.View):
    def __init__(self, host: discord.Member, sheet_manager, map_emojis: dict):
        super().__init__(timeout=None)
        self.host = host
        self.sheet_manager = sheet_manager
        self.map_emojis = map_emojis
        self.participants = {host.id: host.display_name}
        self.map_votes = {}
        self.message = None 

    async def register_vote(self, interaction: discord.Interaction, user_id: int, map_name: str):
        self.map_votes[user_id] = map_name
        if self.message:
            await self.update_embed(original_message=self.message)

    async def update_embed(self, interaction: discord.Interaction = None, original_message: discord.Message = None):
        if interaction:
            embed = interaction.message.embeds[0]
            target_msg = interaction.message
        elif original_message:
            embed = original_message.embeds[0]
            target_msg = original_message
        else:
            return
            
        all_players = list(self.participants.items())
        main_players = all_players[:MAX_MAIN_PLAYERS]
        reserve_players = all_players[MAX_MAIN_PLAYERS:]

        embed.clear_fields()
        
        main_list_str = "\n".join([f"・<@{p_id}>" for p_id, _ in main_players]) if main_players else "現在参加者なし"
        embed.add_field(name=f"参加者一覧 ({len(main_players)}/{MAX_MAIN_PLAYERS}名)", value=main_list_str, inline=False)
        
        if reserve_players:
            reserve_list_str = "\n".join([f"・<@{p_id}>" for p_id, _ in reserve_players])
            embed.add_field(name=f"補欠一覧 ({len(reserve_players)}名)", value=reserve_list_str, inline=False)
        
        main_player_ids = [p[0] for p in main_players]
        vote_count = len([uid for uid in self.map_votes.keys() if uid in main_player_ids])
        vote_guide = "「参加 / 投票する」ボタンを押すと、マップ投票メニューが出現します。\n" \
                     "マップを仮選択後、**【🗳️ 投票】**ボタンを押して完了してください。\n" \
                     f"*(現在の本参加者の投票完了: **{vote_count} / {len(main_players)}名**)*"
        embed.add_field(name="【マップ投票】", value=vote_guide, inline=False)
        
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif original_message:
            await target_msg.edit(embed=embed, view=self)

    @discord.ui.button(label="参加 / 投票する", style=discord.ButtonStyle.success, custom_id="civ_join_btn", row=0)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        await interaction.response.defer(ephemeral=True)
        
        try:
            players_info = self.sheet_manager.get_player_scores([user.id])
            if players_info.get(user.id) is None:
                await interaction.followup.send(
                    "⚠️ **チームの戦力バランスを計算するため、事前に登録が必要です。**\n"
                    "管理者が設置したパネルからプレイヤー登録し、再度ボタンを押してください！",
                    ephemeral=True
                )
                return

            if user.id not in self.participants:
                is_reserve = len(self.participants) >= MAX_MAIN_PLAYERS
                self.participants[user.id] = user.display_name
                await self.update_embed(original_message=interaction.message)
                
                if is_reserve:
                    msg = "✅ 参加登録しました！\n" \
                          "※現在参加枠が埋まっているため、**【補欠枠】**での登録となります。\n" \
                          "（本参加者に辞退者が出た場合は、先着順で自動的に繰り上がります）\n\n" \
                          "下のメニューからプレイしたいマップを選択し、**【🗳️ 投票】**ボタンを押してください。"
                else:
                    msg = "✅ 参加登録しました！\n" \
                          "下のメニューからプレイしたいマップを選択し、**【🗳️ 投票】**ボタンを押してください。"
            else:
                msg = "✅ あなたは既に参加メンバー（または補欠）に登録されています。\n" \
                      "マップの投票先を設定・変更したい場合は、以下から選び直して**【🗳️ 投票】**ボタンを押してください。"

            vote_view = MapVoteView(self.map_emojis, main_matchmaker_view=self)
            await interaction.followup.send(content=msg, view=vote_view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ データベースの確認中にエラーが発生しました: {e}", ephemeral=True)

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.danger, custom_id="civ_leave_btn", row=0)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user.id == self.host.id:
            await interaction.response.send_message("⚠️ ホスト（募集者）は参加を辞退することはできません。キャンセルしたい場合は「募集をキャンセル」を押してください。", ephemeral=True)
            return

        if user.id in self.participants:
            del self.participants[user.id]
            if user.id in self.map_votes:
                del self.map_votes[user.id]
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

        all_players = list(self.participants.keys())
        main_players = all_players[:MAX_MAIN_PLAYERS]

        if len(main_players) < 2:
            await interaction.response.send_message("チームを分けるには最低2人の本参加プレイヤーが必要です！", ephemeral=True)
            return
            
        if len(main_players) % 2 != 0:
            await interaction.response.send_message(
                f"⚠️ 現在の本参加者は **{len(main_players)}名（奇数）** です。\n"
                "対等なチーム分けを行うには人数が偶数である必要があります。メンバーが揃うまでお待ちください。",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        # マップ投票の集計
        map_vote_counts = {name: 0 for name in self.map_emojis.keys()}
        for user_id, map_name in self.map_votes.items():
            if user_id in main_players and map_name in map_vote_counts:
                map_vote_counts[map_name] += 1

        if map_vote_counts and max(map_vote_counts.values()) > 0:
            max_vote_val = max(map_vote_counts.values())
            voted_maps = [k for k, v in map_vote_counts.items() if v == max_vote_val]
            chosen_map = random.choice(voted_maps)
            map_result_str = f"🗺️ 本日の戦場: **{chosen_map}** （{max_vote_val}票獲得）"
        else:
            chosen_map = "ランダム" # 💡 未投票時のバグ修正
            map_result_str = f"🗺️ 本日の戦場: **未投票（ランダム等）**"

        # チーム分け実行
        players_info = self.sheet_manager.get_player_scores(main_players)
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
        result_embed.set_footer(text="GLHF!")

        for child in self.children:
            child.disabled = True
        await interaction.followup.edit_message(message_id=interaction.message.id, view=self)
        await interaction.followup.send(content=f"ホスト <@{self.host.id}> がチームを確定しました！", embed=result_embed)

        # ----------------------------------------------------
        # 📊 統計データの構築とスプレッドシートへの記録
        # ----------------------------------------------------
        try:
            # 💡 修正: 確実に日本時間(JST)になるようにタイムゾーンを指定
            JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')
            now = datetime.datetime.now(JST)
            
            match_id = f"MATCH-{now.strftime('%Y%m%d-%H%M%S')}"
            
            match_data = {
                "match_id": match_id,
                "timestamp": now.strftime('%Y-%m-%d %H:%M:%S'),
                "host_id": self.host.id,
                "selected_map": chosen_map,
                "participant_count": len(main_players), # 補欠を除いた本参加人数
                "total_votes": sum(map_vote_counts.values()),
                "map_votes": map_vote_counts
            }
            
            map_names = list(self.map_emojis.keys())
            # record_match_log メソッドが存在すれば実行
            if hasattr(self.sheet_manager, "record_match_log"):
                self.sheet_manager.record_match_log(match_data, map_names)
            
        except Exception as e:
            print(f"[WARNING] 統計データの記録中にエラーが発生しました: {e}")

        # ----------------------------------------------------
        # 🎲 BAN/PICK の開始 (別ファイルからインポートして実行)
        # ----------------------------------------------------
        from cogs.banpick import BanPickStartView
        
        bp_view = BanPickStartView(
            host=self.host, 
            team_a=team_a, 
            team_b=team_b, 
            sheet_manager=self.sheet_manager
        )
        
        await interaction.followup.send(
            content=f"ホスト <@{self.host.id}> は、待機場に全員が揃ったら下のボタンを押してBAN/PICKを開始してください。\n"
                    f"*(※自動的にチームVCへ移動します)*", 
            view=bp_view
        )

    @discord.ui.button(label="募集をキャンセル", style=discord.ButtonStyle.danger, custom_id="civ_cancel_btn", row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("このボタンは募集ホストのみ押すことができます。", ephemeral=True)
            return
            
        await interaction.response.send_message(f"⚠️ ホスト <@{self.host.id}> が今回の募集をキャンセルしました。")
        await interaction.message.delete()


# ==========================================
# 4. Discord UIコンポーネント (登録系)
# ==========================================
class SkillDropdown(discord.ui.Select):
    def __init__(self, flg_list: list):
        max_vals = len(flg_list) if len(flg_list) > 0 else 1
        options = []
        for item in flg_list:
            short_desc = str(item.get("description", ""))
            if len(short_desc) > 50:
                short_desc = short_desc[:47] + "..."
            
            flg_name = str(item.get("flg_name", ""))
            label_text = flg_name.replace('FLG_', '')
            score = item.get("score", 0)
            
            if not label_text:
                label_text = "未設定"
            if not flg_name:
                flg_name = "none"
            
            options.append(discord.SelectOption(
                label=label_text,
                value=flg_name,
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

    @discord.ui.button(label="登録する", style=discord.ButtonStyle.primary, custom_id="civ_start_register_btn")
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

    @app_commands.command(name="civ_match", description="Civ6マルチプレイの参加登録とマップ投票、チーム分けを開始します。")
    @app_commands.describe(role="募集時にメンションを送信したいロールを指定します (省略時はメンションなし)")
    async def civ_match(self, interaction: discord.Interaction, role: discord.Role = None):
        host = interaction.user

        if role:
            mention_str = f"{role.mention}\n\n"
        else:
            mention_str = ""

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
                        "以下のボタンから参加表明・マップ投票を行ってください。",
            color=discord.Color.blue()
        )
        embed.add_field(name=f"参加者一覧 (1/{MAX_MAIN_PLAYERS}名)", value=f"・<@{host.id}>", inline=False)
        
        vote_guide = "「参加 / 投票する」ボタンを押すと、自分専用のマップ投票メニューが出現します。\n" \
                     "マップを仮選択後、**【🗳️ 投票】**ボタンを押して完了してください。\n" \
                     "*(現在の本参加者の投票完了: **0 / 1名**)*"
        embed.add_field(name="【マップ投票】", value=vote_guide, inline=False)
        
        view = MatchmakerView(host=host, sheet_manager=self.bot.sheet_manager, map_emojis=map_emojis)
        
        await interaction.response.send_message(content=mention_str if mention_str else None, embed=embed, view=view)
        view.message = await interaction.original_response()

        host_vote_view = MapVoteView(map_emojis, main_matchmaker_view=view)
        await interaction.followup.send(
            content=f"✅ <@{host.id}> さん、募集を開始しました！\n"
                    "続けて、下のメニューからプレイしたいマップに投票してください。",
            view=host_vote_view,
            ephemeral=True
        )

    @app_commands.command(name="civ_setup_register", description="【管理者専用】プレイヤー用の登録パネルを設置します。")
    @app_commands.default_permissions(administrator=True)
    async def civ_setup_register(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚔️ Civ6 プレイヤー登録 ⚔️",
            description="Civ6マルチサーバーへようこそ！\n"
                        "プレイヤー全員に登録をお願いしています。\n\n"
                        "以下のボタンから登録を済ませてください！\n"
                        "※未登録のプレイヤーは、募集時の「参加ボタン」が押せなくなります。",
            color=discord.Color.dark_purple()
        )
        embed.add_field(
            name="📝 登録・更新方法",
            value="1. 下の「登録する」ボタンを押す。\n"
                  "2. ドロップダウンから項目を選択（複数可）。\n"
                  "3. 送信ボタンを押して「登録完了」と表示されればOKです！",
            inline=False
        )

        view = RegisterChannelView(self.bot.sheet_manager)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="civ_banpick", description="BAN/PICKツールを単独で起動します。（チーム分け機能を使わずに直接開始する場合）")
    @app_commands.describe(
        rep_a="🔵 チームAの代表者（BAN選択の操作を行う人）",
        rep_b="🔴 チームBの代表者（BAN選択の操作を行う人）",
        team_size="チームの人数 (4v4なら4, 5v5なら5。※BAN数の自動計算に使われます)"
    )
    async def civ_banpick(self, interaction: discord.Interaction, rep_a: discord.Member, rep_b: discord.Member, team_size: int = 4):
        # banpick.py がBAN数を「チーム人数 - 1」で計算できるよう、ダミーの要素でリストの長さを調整する
        team_a_ids = [rep_a.id] + [0] * (team_size - 1)
        team_b_ids = [rep_b.id] + [0] * (team_size - 1)
        
        # 仮のルールリスト (将来的にシートから取得可能にする設計)
        rules = [
            {"ルール名": "グローバルBAN ドラフト", "絵文字": "📝", "説明（備考）": "今回実装したグローバルBAN対応のドラフトモード"},
            {"ルール名": "完全ランダム", "絵文字": "🎲", "説明（備考）": "全員がランダムな指導者でプレイします。"},
            {"ルール名": "1Ban 3Pick", "絵文字": "🚫", "説明（備考）": "各チーム1つの文明をBANし、3つの文明から1つを選びます。"}
        ]
        
        # モード選択Viewの呼び出し
        bp_view = BanPickView(
            host=interaction.user,
            rules=rules,
            team_a=team_a_ids,
            team_b=team_b_ids,
            sheet_manager=self.bot.sheet_manager
        )
        
        await interaction.response.send_message(
            content=f"⚔️ **BAN/PICKツール (手動起動)**\n"
                    f"ホスト <@{interaction.user.id}> は、以下のメニューからBAN/PICKのモードを選択してください。\n"
                    f"*(🔵 チームA代表: {rep_a.mention} / 🔴 チームB代表: {rep_b.mention})*",
            view=bp_view
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(MatchmakerCog(bot))
    bot.add_view(RegisterChannelView(bot.sheet_manager))
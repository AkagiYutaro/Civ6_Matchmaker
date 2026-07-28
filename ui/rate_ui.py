import discord

class RateCheckButton(discord.ui.Button):
    def __init__(self, rate_results: dict):
        super().__init__(style=discord.ButtonStyle.secondary, label="📊 自分のレート変動を確認", custom_id="check_rate")
        self.rate_results = rate_results

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if user_id not in self.rate_results:
            return await interaction.response.send_message("あなたは今回の対戦メンバーに含まれていません。", ephemeral=True)
            
        data = self.rate_results[user_id]
        diff = data['diff']
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        
        embed = discord.Embed(
            title="📊 あなたのレート変動",
            description=f"**{data['old']}** ➔ **{data['new']}** ({diff_str})",
            color=discord.Color.green() if diff >= 0 else discord.Color.red()
        )
        # 本人にだけ(ephemeral)結果を表示する
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DraftCheckButton(discord.ui.Button):
    def __init__(self, manager):
        super().__init__(style=discord.ButtonStyle.primary, label="📜 配布ドラフトを確認", custom_id="check_draft")
        self.manager = manager

    async def callback(self, interaction: discord.Interaction):
        survivors = self.manager.survivors
        half_idx = (len(survivors) + 1) // 2
        list_a = survivors[:half_idx]
        list_b = survivors[half_idx:]

        embed = discord.Embed(title="📜 この試合のドラフト候補一覧", color=discord.Color.blurple())
        
        def add_team_fields(target_embed, team_label, leader_list):
            chunk_size = 20
            chunks = [leader_list[i:i+chunk_size] for i in range(0, len(leader_list), chunk_size)]
            total_pages = max(1, len(chunks))
            for i, chunk in enumerate(chunks, 1):
                names = []
                for L in chunk:
                    emoji = L.get('emoji_text', '')
                    name = L['clean_name']
                    # 万が一final_disp_noがない場合のフォールバック
                    disp_no = L.get('final_disp_no', L.get('target_disp_no', 0))
                    names.append(f"{disp_no}. {emoji} {name}" if emoji else f"{disp_no}. {name}")
                
                val = "\n".join(names) if names else "なし"
                page_title = f"{team_label} - {i}/{total_pages}" if total_pages > 1 else team_label
                target_embed.add_field(name=page_title, value=val, inline=True)

        add_team_fields(embed, "🔵 チームA ピック候補", list_a)
        add_team_fields(embed, "🔴 チームB ピック候補", list_b)
        
        # 本人にだけ表示する
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RateCheckView(discord.ui.View):
    # 💡 修正: ドラフト表示用に manager を受け取るように変更
    def __init__(self, rate_results: dict, manager):
        super().__init__(timeout=None)
        self.add_item(RateCheckButton(rate_results))
        self.add_item(DraftCheckButton(manager))
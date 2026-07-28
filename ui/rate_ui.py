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

        embed = discord.Embed(title="📜 ドラフト一覧", color=discord.Color.blurple())
        
        chunk_size = 20
        chunks_a = [list_a[i:i+chunk_size] for i in range(0, len(list_a), chunk_size)]
        chunks_b = [list_b[i:i+chunk_size] for i in range(0, len(list_b), chunk_size)]
        
        max_chunks = max(len(chunks_a), len(chunks_b))
        
        # AとBを交互に追加して、必ず2列の左右対称になるよう強制制御する
        for i in range(max_chunks):
            # チームAの追加
            if i < len(chunks_a):
                names = []
                for L in chunks_a[i]:
                    emoji = L.get('emoji_text', '')
                    name = L['clean_name']
                    disp_no = L.get('final_disp_no', L.get('target_disp_no', 0))
                    names.append(f"{disp_no}. {emoji} {name}" if emoji else f"{disp_no}. {name}")
                val = "\n".join(names) if names else "なし"
                title = f"🔵 チームA ({i+1}/{len(chunks_a)})" if len(chunks_a) > 1 else "🔵 チームA"
                embed.add_field(name=title, value=val, inline=True)
            else:
                embed.add_field(name="\u200B", value="\u200B", inline=True)

            # チームBの追加
            if i < len(chunks_b):
                names = []
                for L in chunks_b[i]:
                    emoji = L.get('emoji_text', '')
                    name = L['clean_name']
                    disp_no = L.get('final_disp_no', L.get('target_disp_no', 0))
                    names.append(f"{disp_no}. {emoji} {name}" if emoji else f"{disp_no}. {name}")
                val = "\n".join(names) if names else "なし"
                title = f"🔴 チームB ({i+1}/{len(chunks_b)})" if len(chunks_b) > 1 else "🔴 チームB"
                embed.add_field(name=title, value=val, inline=True)
            else:
                embed.add_field(name="\u200B", value="\u200B", inline=True)
                
            # 次のページ(チャンク)を強制的に下の行にするための不可視フィールド
            if i < max_chunks - 1:
                embed.add_field(name="\u200B", value="\u200B", inline=False)

        # 本人にだけ表示する
        await interaction.response.send_message(embed=embed, ephemeral=True)

class RateCheckView(discord.ui.View):
    # 💡 修正: ドラフト表示用に manager を受け取るように変更
    def __init__(self, rate_results: dict, manager):
        super().__init__(timeout=None)
        self.add_item(RateCheckButton(rate_results))
        self.add_item(DraftCheckButton(manager))
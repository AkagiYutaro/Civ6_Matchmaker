import random
import asyncio
import gspread
import logging
import discord

logger = logging.getLogger('discord.banpick')

# ==========================================
# スプレッドシート カウントアップ用非同期処理
# ==========================================
async def update_ban_count_in_sheet(sheet_manager, banned_names):
    if not sheet_manager or not banned_names:
        return
        
    def _update():
        try:
            ws = sheet_manager.sheet.worksheet("指導者")
            records = ws.get_all_records()
            # ヘッダーの取得（空白文字等の除去）
            headers = [str(h).strip() for h in ws.row_values(1)]
            
            needs_update = False
            if "BAN回数" not in headers:
                headers.append("BAN回数")
                needs_update = True
            if "PICK回数" not in headers:
                headers.append("PICK回数")
                needs_update = True
                
            if needs_update:
                ws.update("A1", [headers])
                
            ban_col_idx = headers.index("BAN回数") + 1
            
            updates = []
            for row_idx, row in enumerate(records, start=2):
                leader_name = str(row.get("指導者名", "")).strip()
                if leader_name in banned_names:
                    current_val = row.get("BAN回数", 0)
                    try:
                        count = int(current_val) if current_val != "" else 0
                    except ValueError:
                        count = 0
                    
                    updates.append({
                        'range': gspread.utils.rowcol_to_a1(row_idx, ban_col_idx),
                        'values': [[count + 1]]
                    })
                    
            if updates:
                ws.batch_update(updates)
                logger.info(f"[SUCCESS] スプレッドシートのBAN回数を更新しました: {banned_names}")
        except Exception as e:
            logger.error(f"[ERROR] BAN回数の更新に失敗: {e}")

    await asyncio.to_thread(_update)


# ==========================================
# リーダーリスト整形ロジック
# ==========================================
def format_leader_list(uid_list, all_leaders):
    names = []
    for i, uid in enumerate(uid_list, start=1):
        leader = next((l for l in all_leaders if l['uid'] == uid), None)
        if leader:
            emoji = leader.get('emoji_text', '')
            name = leader['clean_name']
            names.append(f"{i}. {emoji} {name}" if emoji else f"{i}. {name}")
    return "\n".join(names) if names else "なし"


def split_and_number_leaders(leaders, number_key):
    half_idx = (len(leaders) + 1) // 2
    list_a = leaders[:half_idx]
    list_b = leaders[half_idx:]
    
    for i, L in enumerate(list_a, start=1):
        L[number_key] = i
    for i, L in enumerate(list_b, start=1):
        L[number_key] = i
        
    return list_a, list_b


def prepare_leader_data(raw_leaders, client=None):
    all_leaders = []
    for i, L in enumerate(raw_leaders):
        leader_data = L.copy()
        
        no_val = str(leader_data.get("No", "")).strip()
        if not no_val: no_val = str(i + 1)
        
        leader_name = leader_data.get('指導者名', 'Unknown')
        
        emoji_nm = str(leader_data.get('Emoji_Discord_Nm', '')).strip()
        emoji_id = str(leader_data.get('Emoji_Discord_ID', '')).strip()
        
        emoji_obj = None
        emoji_text = ""
        
        if emoji_nm and emoji_id.isdigit():
            try:
                e_id = int(emoji_id)
                # 💡 修正: 自分で組み立てるのをやめ、BOTが認識している「本物の絵文字データ」を直接取得する
                if client:
                    fetched_emoji = client.get_emoji(e_id)
                    if fetched_emoji:
                        emoji_obj = fetched_emoji # 本物をそのままUIに渡す
                        # アニメーション(GIF)かどうかも自動判定してテキスト化
                        a_prefix = "a" if fetched_emoji.animated else ""
                        emoji_text = f"<{a_prefix}:{fetched_emoji.name}:{fetched_emoji.id}>"
                    else:
                        logger.warning(f"BOTがアクセスできない絵文字IDです。非表示にします: {emoji_nm} ({e_id})")
                        emoji_obj = None
                        emoji_text = ""
                else:
                    # fallback
                    emoji_obj = discord.PartialEmoji(name=emoji_nm, id=e_id)
                    emoji_text = f"<:{emoji_nm}:{e_id}>"
            except Exception as e:
                logger.warning(f"絵文字パース失敗 [{emoji_nm}]: {e}")
        elif emoji_id and not emoji_id.isdigit():
            emoji_obj = emoji_id
            emoji_text = emoji_id
        
        unique_id = f"leader_id_{i}_{leader_name}"
        
        leader_data['clean_name'] = leader_name
        leader_data['No'] = no_val
        leader_data['uid'] = unique_id
        leader_data['emoji_obj'] = emoji_obj
        leader_data['emoji_text'] = emoji_text
        
        all_leaders.append(leader_data)

    global_pool = []
    for L in all_leaders:
        val = L.get("グローバルBANFLG", L.get("グローバルBAN候補"))
        try:
            if int(str(val or 0).strip()) == 1:
                global_pool.append(L)
        except ValueError:
            pass
            
    if len(global_pool) > 25:
        global_pool = global_pool[:25]
    if not global_pool:
        global_pool = all_leaders[:10]
        
    for i, L in enumerate(global_pool, start=1):
        L['global_disp_no'] = i
        
    return all_leaders, global_pool
import random
import asyncio
import gspread
import logging
import discord

logger = logging.getLogger('discord.banpick')

async def update_ban_count_in_sheet(sheet_manager, banned_names):
    """
    BANされた指導者の名前リストを受け取り、非同期でスプレッドシートのBAN回数を更新する。
    """
    if not sheet_manager or not banned_names:
        return
        
    def _update():
        try:
            ws = sheet_manager.sheet.worksheet("指導者")
            records = ws.get_all_records()
            headers = ws.row_values(1)
            
            # BAN回数列、PICK回数列がない場合は自動追加
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


def format_leader_list(uid_list, all_leaders):
    """UIDのリストから、連番＋絵文字＋指導者名の文字列を生成する"""
    names = []
    for i, uid in enumerate(uid_list, start=1):
        leader = next((l for l in all_leaders if l['uid'] == uid), None)
        if leader:
            emoji = leader.get('emoji_text', '')
            name = leader['clean_name']
            names.append(f"{i}. {emoji} {name}" if emoji else f"{i}. {name}")
    return "\n".join(names) if names else "なし"


def split_and_number_leaders(leaders, number_key):
    """リストを半分に分割し、それぞれに指定したキー名で通し番号(1〜)を振る"""
    half_idx = (len(leaders) + 1) // 2
    list_a = leaders[:half_idx]
    list_b = leaders[half_idx:]
    
    for i, L in enumerate(list_a, start=1):
        L[number_key] = i
    for i, L in enumerate(list_b, start=1):
        L[number_key] = i
        
    return list_a, list_b


def prepare_leader_data(raw_leaders):
    """スプレッドシートの生データから、全指導者リストとグローバルBAN候補リストを構築する"""
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
                emoji_obj = discord.PartialEmoji(name=emoji_nm, id=int(emoji_id))
                emoji_text = f"<:{emoji_nm}:{emoji_id}>"
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
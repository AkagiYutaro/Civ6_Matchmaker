import gspread
from google.oauth2.service_account import Credentials
import os
import logging
import datetime

logger = logging.getLogger('discord.sheet_manager')

class SheetManager:
    # プレイヤーデータシートの基本ヘッダー
    STATIC_HEADERS = ["CivNo", "Discord_ID", "プレイヤー名", "レート"]

    def __init__(self, spreadsheet_key: str, creds_file: str):
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if not os.path.exists(creds_file):
            raise FileNotFoundError(f"[ERROR] 認証ファイル '{creds_file}' が見つかりません。")
        try:
            self.creds = Credentials.from_service_account_file(creds_file, scopes=self.scope)
            self.client = gspread.authorize(self.creds)
            self.sheet = self.client.open_by_key(spreadsheet_key)
            logger.info("[SUCCESS] スプレッドシートへの接続に成功しました。")
        except Exception as e:
            logger.error(f"[CRITICAL ERROR] スプレッドシートの認証・接続に失敗: {e}")
            raise e

    def get_map_emojis(self) -> dict:
        try:
            ws = self.sheet.worksheet("MAP")
            records = ws.get_all_records()
            map_data = {}
            for row in records:
                map_name = str(row.get("マップ名", "")).strip()
                emoji = str(row.get("絵文字", "")).strip()
                if map_name and emoji:
                    map_data[map_name] = emoji
            return map_data
        except Exception as e:
            logger.error(f"[ERROR] MAPシートの取得に失敗しました: {e}")
            return {}

    def get_leaders(self) -> list:
        try:
            ws = self.sheet.worksheet("指導者")
            records = ws.get_all_records()
            leaders = []
            for row in records:
                no_val = str(row.get("No", "")).strip()
                leader_name = str(row.get("指導者名", "")).strip()
                civ_name = str(row.get("文明名", "")).strip()
                
                if leader_name:
                    leaders.append({
                        "No": no_val,
                        "指導者名": leader_name,
                        "文明名": civ_name,
                        "絵文字": str(row.get("絵文字", "")).strip(),
                        "Emoji_Discord_Nm": str(row.get("Emoji_Discord_Nm", "")).strip(),
                        "Emoji_Discord_ID": str(row.get("Emoji_Discord_ID", "")).strip(),
                        "グローバルBANFLG": row.get("グローバルBANFLG", 0)
                    })
            return leaders
        except Exception as e:
            logger.warning(f"[WARNING] 指導者シートの取得に失敗しました: {e}")
            return []

    def get_master_categories(self) -> dict:
        try:
            ws = self.sheet.worksheet("マスタ設定")
            records = ws.get_all_records()
            categories = {}
            for r in records:
                title = str(r.get("タイトル", "")).strip()
                condition = str(r.get("条件", "")).strip()
                civ_no = str(r.get("CivNO", "")).strip()
                
                if not title or not condition: 
                    continue
                
                if title not in categories:
                    categories[title] = []
                
                categories[title].append({
                    "CivNO": civ_no,
                    "条件": condition,
                    "配点": int(r.get("配点", 0)) if str(r.get("配点", "")).isdigit() else 0,
                    "備考": str(r.get("備考", "")).strip()
                })
            return categories
        except Exception as e:
            logger.error(f"[ERROR] マスタ設定カテゴリの取得に失敗: {e}")
            return {}

    def get_master_config(self) -> list:
        try:
            ws = self.sheet.worksheet("マスタ設定")
            return ws.get_all_records()
        except:
            return []

    def get_player_scores(self, discord_ids: list) -> dict:
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            player_scores = {}
            for p_id in discord_ids:
                str_id = str(p_id)
                player_row = next((p for p in all_players if str(p.get("Discord_ID")) == str_id), None)
                if player_row:
                    rate_val = player_row.get("レート", 1500)
                    score = int(rate_val) if str(rate_val).isdigit() else 1500
                    player_scores[p_id] = {"name": player_row.get("プレイヤー名", f"ID: {str_id}"), "score": score}
                else:
                    player_scores[p_id] = None
            return player_scores
        except Exception as e:
            logger.error(f"[ERROR] プレイヤーデータの読み込み失敗: {e}")
            raise e

    def register_or_update_player(self, discord_id: int, player_name: str, active_flgs=None, **kwargs) -> bool:
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            str_id = str(discord_id)
            
            if active_flgs is None:
                active_flgs = kwargs.get('active_flgs', [])

            row_idx = next((idx for idx, p in enumerate(all_players, start=2) if str(p.get("Discord_ID")) == str_id), None)
            
            def get_civ_no(player_data):
                val = player_data.get("CivNo", player_data.get("CivNO", 0))
                return int(str(val).strip()) if str(val).strip().isdigit() else 0

            if row_idx:
                target_civ_no = get_civ_no(all_players[row_idx - 2])
            else:
                target_civ_no = max([get_civ_no(p) for p in all_players], default=0) + 1
            
            ws_master = self.sheet.worksheet("マスタ設定")
            master_records = ws_master.get_all_records()
            
            master_dict = {}
            master_titles = []
            for m in master_records:
                c_no = str(m.get("CivNO", "")).strip()
                title = str(m.get("タイトル", "")).strip()
                if c_no:
                    master_dict[c_no] = {
                        "タイトル": title,
                        "条件": str(m.get("条件", "")).strip(),
                        "配点": int(m.get("配点", 0)) if str(m.get("配点", "")).isdigit() else 0
                    }
                if title and title not in master_titles:
                    master_titles.append(title)
                    
            calculated_rate = sum(master_dict[c_no]["配点"] for c_no in active_flgs if c_no in master_dict) if active_flgs else 1500

            player_choices = {}
            if active_flgs:
                for c_no in active_flgs:
                    if c_no in master_dict:
                        t = master_dict[c_no]["タイトル"]
                        cond = master_dict[c_no]["条件"]
                        player_choices[t] = cond

            headers = [str(h).strip() for h in players_ws.row_values(1)]
            
            needs_update_header = False
            if "レート" not in headers:
                headers.append("レート")
                needs_update_header = True
                
            for t in master_titles:
                if t not in headers:
                    headers.append(t)
                    needs_update_header = True
                    
            if needs_update_header:
                try:
                    players_ws.update("A1", [headers])
                except TypeError:
                    players_ws.update([headers], "A1")

            row_data = []
            for h in headers:
                if h in ["CivNo", "CivNO"]:
                    row_data.append(target_civ_no)
                elif h == "Discord_ID":
                    row_data.append(str_id)
                elif h == "プレイヤー名":
                    row_data.append(player_name)
                elif h == "レート":
                    row_data.append(calculated_rate)
                elif h in master_titles:
                    row_data.append(player_choices.get(h, ""))
                else:
                    if row_idx:
                        row_data.append(all_players[row_idx - 2].get(h, ""))
                    else:
                        row_data.append("")
            
            if row_idx:
                range_str = f"A{row_idx}:{gspread.utils.rowcol_to_a1(row_idx, len(row_data))}"
                try:
                    players_ws.update(range_str, [row_data])
                except TypeError:
                    players_ws.update([row_data], range_str)
            else:
                players_ws.append_row(row_data)
                
            logger.info(f"[SUCCESS] プレイヤーデータを保存しました: {player_name} (Rate: {calculated_rate})")
            return True
        except Exception as e:
            logger.error(f"[ERROR] プレイヤーデータの保存に失敗しました: {e}")
            return False

    def _ensure_match_log_sheet(self, map_names: list) -> gspread.Worksheet:
        try:
            ws = self.sheet.worksheet("対戦ログ")
        except gspread.exceptions.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title="対戦ログ", rows="100", cols="20")
        current_headers = [str(h).strip() for h in ws.row_values(1)]
        base_headers = ["対戦ID", "実行日時", "募集ホストID", "採用マップ", "参加人数", "総投票数"]
        if not current_headers:
            ws.update("A1", [base_headers + map_names])
            return ws
        headers = current_headers.copy()
        for m_name in map_names:
            if m_name not in headers:
                headers.append(m_name)
        if len(headers) > len(current_headers):
            try:
                ws.update("A1", [headers])
            except TypeError:
                ws.update([headers], "A1")
        return ws

    def record_match_log(self, match_data: dict, map_names: list) -> bool:
        try:
            ws = self._ensure_match_log_sheet(map_names)
            headers = [str(h).strip() for h in ws.row_values(1)]
            row_data = []
            for h in headers:
                if h == "対戦ID": row_data.append(match_data.get("match_id", ""))
                elif h == "実行日時": row_data.append(match_data.get("timestamp", ""))
                elif h == "募集ホストID": row_data.append(str(match_data.get("host_id", "")))
                elif h == "採用マップ": row_data.append(match_data.get("selected_map", ""))
                elif h == "参加人数": row_data.append(match_data.get("participant_count", 0))
                elif h == "総投票数": row_data.append(match_data.get("total_votes", 0))
                elif h in map_names:
                    row_data.append(match_data.get("map_votes", {}).get(h, 0))
                else:
                    row_data.append("")
            ws.append_row(row_data)
            return True
        except Exception as e:
            logger.error(f"[ERROR] 対戦ログの記録失敗: {e}")
            return False

    def update_map_stats(self, chosen_map: str, map_votes_count: dict):
        try:
            ws = self.sheet.worksheet("MAP")
            headers = [str(h).strip() for h in ws.row_values(1)]
            needs_update = False
            if "採用回数" not in headers:
                headers.append("採用回数")
                needs_update = True
            if "累計獲得票数" not in headers:
                headers.append("累計獲得票数")
                needs_update = True
                
            if needs_update:
                try:
                    ws.update("A1", [headers])
                except TypeError:
                    ws.update([headers], "A1")

            col_map_name = headers.index("マップ名") if "マップ名" in headers else 0
            col_picked = headers.index("採用回数")
            col_votes = headers.index("累計獲得票数")
            all_values = ws.get_all_values()
            
            for row_idx, row in enumerate(all_values):
                if row_idx == 0: continue
                while len(row) < len(headers):
                    row.append("")
                map_name = str(row[col_map_name]).strip()
                if map_name:
                    current_picked = int(row[col_picked]) if str(row[col_picked]).isdigit() else 0
                    current_votes = int(row[col_votes]) if str(row[col_votes]).isdigit() else 0
                    row[col_picked] = current_picked + (1 if map_name == chosen_map else 0)
                    row[col_votes] = current_votes + map_votes_count.get(map_name, 0)
            
            range_str = f"A1:{gspread.utils.rowcol_to_a1(len(all_values), len(headers))}"
            try:
                ws.update(range_str, all_values)
            except TypeError:
                ws.update(all_values, range_str)
        except Exception as e:
            logger.error(f"[ERROR] MAPシートの統計更新に失敗: {e}")

    def record_match_details(self, details_data: list) -> bool:
        try:
            try:
                ws = self.sheet.worksheet("対戦詳細ログ")
            except gspread.exceptions.WorksheetNotFound:
                ws = self.sheet.add_worksheet(title="対戦詳細ログ", rows="100", cols="7")
                headers = ["対戦ID", "実行日時", "プレイヤーID", "プレイヤー名", "所属チーム", "PICK指導者", "勝敗"]
                ws.update("A1", [headers])

            if details_data:
                ws.append_rows(details_data)
            return True
        except Exception as e:
            logger.error(f"[ERROR] 対戦詳細ログの記録に失敗しました: {e}")
            return False

    def update_match_result(self, match_id: str, win_team: str) -> bool:
        try:
            ws = self.sheet.worksheet("対戦詳細ログ")
            records = ws.get_all_records()
            headers = [str(h).strip() for h in ws.row_values(1)]
            if "勝敗" not in headers:
                return False
            col_idx = headers.index("勝敗") + 1
            updates = []
            for row_idx, row in enumerate(records, start=2):
                if str(row.get("対戦ID", "")) == match_id:
                    team = str(row.get("所属チーム", ""))
                    result = "WIN" if team == win_team else "LOSE"
                    updates.append({
                        'range': gspread.utils.rowcol_to_a1(row_idx, col_idx),
                        'values': [[result]]
                    })
            if updates:
                ws.batch_update(updates)
            return True
        except Exception as e:
            logger.error(f"[ERROR] 勝敗の記録に失敗しました: {e}")
            return False

    def get_next_match_id(self) -> str:
        """対戦ログシートから次の対戦ID（#〇〇）を自動採番する"""
        try:
            ws = self.sheet.worksheet("対戦ログ")
            records = ws.get_all_values()
            return f"#{len(records)}"
        except Exception:
            return "#1"

    def update_pick_count(self, picked_leader_names: list):
        if not picked_leader_names: return
        try:
            ws = self.sheet.worksheet("指導者")
            records = ws.get_all_records()
            headers = [str(h).strip() for h in ws.row_values(1)]
            if "PICK回数" not in headers:
                headers.append("PICK回数")
                ws.update("A1", [headers])
            pick_col_idx = headers.index("PICK回数") + 1
            updates = []
            for row_idx, row in enumerate(records, start=2):
                leader_name = str(row.get("指導者名", "")).strip()
                if leader_name in picked_leader_names:
                    current_val = row.get("PICK回数", 0)
                    try:
                        count = int(current_val) if current_val != "" else 0
                    except ValueError:
                        count = 0
                    updates.append({
                        'range': gspread.utils.rowcol_to_a1(row_idx, pick_col_idx),
                        'values': [[count + 1]]
                    })
            if updates:
                ws.batch_update(updates)
        except Exception as e:
            print(f"[ERROR] PICK回数の更新に失敗: {e}")

    def get_player_rates(self, discord_ids: list) -> dict:
        default_rate = 1500
        rates = {did: default_rate for did in discord_ids}
        try:
            ws = self.sheet.worksheet("プレイヤーデータ")
            records = ws.get_all_records()
            for row in records:
                did_str = str(row.get("Discord_ID", ""))
                if did_str.isdigit() and int(did_str) in discord_ids:
                    r = row.get("レート", default_rate)
                    rates[int(did_str)] = int(r) if str(r).strip().isdigit() else default_rate
        except Exception as e:
            print(f"[ERROR] レート取得失敗: {e}")
        return rates

    def update_player_rates(self, rate_updates: dict) -> bool:
        try:
            ws = self.sheet.worksheet("プレイヤーデータ")
            records = ws.get_all_records()
            headers = [str(h).strip() for h in ws.row_values(1)]
            if "レート" not in headers:
                headers.append("レート")
                ws.update("A1", [headers])
            rate_col_idx = headers.index("レート") + 1
            updates = []
            for row_idx, row in enumerate(records, start=2):
                did_str = str(row.get("Discord_ID", ""))
                if did_str.isdigit() and int(did_str) in rate_updates:
                    new_rate = rate_updates[int(did_str)]
                    updates.append({
                        'range': gspread.utils.rowcol_to_a1(row_idx, rate_col_idx),
                        'values': [[new_rate]]
                    })
            if updates:
                ws.batch_update(updates)
            return True
        except Exception as e:
            print(f"[ERROR] レートの更新に失敗: {e}")
            return False

    def get_player_summary_stats(self, discord_id: int) -> dict:
        try:
            ws = self.sheet.worksheet("集計")
            records = ws.get_all_records()
            str_id = str(discord_id)
            for row in records:
                if str(row.get("プレイヤーID", "")) == str_id:
                    return row
            return None
        except Exception as e:
            logger.error(f"[ERROR] 集計シートのステータス取得に失敗: {e}")
            return None
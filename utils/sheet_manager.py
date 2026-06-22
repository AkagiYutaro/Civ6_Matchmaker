import gspread
from google.oauth2.service_account import Credentials
import os
import logging

logger = logging.getLogger('discord.sheet_manager')

class SheetManager:
    STATIC_HEADERS = ["CivNo", "Discord_ID", "プレイヤー名", "WIN", "LOSE", "WinRate", "総プレイ数"]

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

    # 👇 ここから追加：指導者データの取得
    def get_leaders(self) -> list:
        """独立した「指導者」シートから文明と指導者の一覧を取得します"""
        try:
            ws = self.sheet.worksheet("指導者")
            records = ws.get_all_records()
            leaders = []
            for row in records:
                # 👇 スプレッドシートから各列を取得
                no_val = str(row.get("No", "")).strip()
                leader_name = str(row.get("指導者名", "")).strip()
                civ_name = str(row.get("文明名", "")).strip()
                
                if leader_name:
                    leaders.append({
                        "No": no_val,
                        "指導者名": leader_name,
                        "文明名": civ_name,
                        "絵文字": str(row.get("絵文字", "")).strip(),
                        # 💡 ここに追加: 新しい列データも抽出して辞書に含める！
                        "Emoji_Discord_Nm": str(row.get("Emoji_Discord_Nm", "")).strip(),
                        "Emoji_Discord_ID": str(row.get("Emoji_Discord_ID", "")).strip(),
                        "グローバルBANFLG": row.get("グローバルBANFLG", 0)
                    })
            return leaders
        except Exception as e:
            print(f"[WARNING] 指導者シートの取得に失敗しました: {e}")
            return []
    # 👆 ここまで追加

    def get_master_config(self) -> list:
        try:
            ws = self.sheet.worksheet("マスタ設定")
            records = ws.get_all_records()
            return [row for row in records if str(row.get("カテゴリ", "")).strip() == "スキル"]
        except Exception as e:
            logger.error(f"[ERROR] マスタ設定の取得に失敗しました: {e}")
            return []

    # 💡 ここに追加: アンケートドロップダウン用にデータを整形して返すメソッド
    def get_master_flgs(self) -> list:
        """アンケート表示用に整形されたFLGリストを取得する"""
        try:
            configs = self.get_master_config()
            flg_list = []
            for item in configs:
                flg_list.append({
                    "flg_name": str(item.get("FLG名", "")).strip(),
                    "score": int(item.get("現在の配点", 0)) if str(item.get("現在の配点", "")).isdigit() else 0,
                    "description": str(item.get("備考", "")).strip()
                })
            return flg_list
        except Exception as e:
            logger.error(f"[ERROR] アンケート用FLG項目の取得に失敗: {e}")
            return []

    def get_player_scores(self, discord_ids: list) -> dict:
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            master_config = self.get_master_config()
            weight_map = {item.get("FLG名", ""): int(item.get("現在の配点", 0)) for item in master_config}
            player_scores = {}
            for p_id in discord_ids:
                str_id = str(p_id)
                player_row = next((p for p in all_players if str(p.get("Discord_ID")) == str_id), None)
                if player_row:
                    score = sum(int(val) * weight_map[col] for col, val in player_row.items() if col in weight_map and str(val).isdigit())
                    player_scores[p_id] = {"name": player_row.get("プレイヤー名", f"ID: {str_id}"), "score": score}
                else:
                    player_scores[p_id] = None
            return player_scores
        except Exception as e:
            logger.error(f"[ERROR] プレイヤースコアの読み込み失敗: {e}")
            raise e

    # 💡 修正: 引数を柔軟に受け取り、エラーなく処理できるように強化
    def register_or_update_player(self, discord_id: int, player_name: str, skill_data=None, active_flgs=None, **kwargs) -> bool:
        try:
            players_ws = self.sheet.worksheet("プレイヤーデータ")
            all_players = players_ws.get_all_records()
            str_id = str(discord_id)
            
            # 引数の柔軟な受け取り対応 (リストが渡された場合や、キーワード引数に対応)
            if active_flgs is None:
                if isinstance(skill_data, list):
                    active_flgs = skill_data
                    skill_data = None
                elif 'active_flgs' in kwargs:
                    active_flgs = kwargs['active_flgs']
                else:
                    active_flgs = []

            row_idx = next((idx for idx, p in enumerate(all_players, start=2) if str(p.get("Discord_ID")) == str_id), None)
            
            # 💡 修正: "CivNo" と "CivNO" の表記揺れを吸収し、確実に数値を取得する関数
            def get_civ_no(player_data):
                val = player_data.get("CivNo", player_data.get("CivNO", 0))
                return int(str(val).strip()) if str(val).strip().isdigit() else 0

            if row_idx:
                target_civ_no = get_civ_no(all_players[row_idx - 2])
            else:
                # 既存プレイヤー全員の番号から最大値を探し、+1 する
                target_civ_no = max([get_civ_no(p) for p in all_players], default=0) + 1
            
            # フラグの設定 (選択されたものを 1 に、それ以外を 0 にする)
            if active_flgs is not None:
                flags = [1 if str(m.get("FLG名", "")).strip() in active_flgs else 0 for m in self.get_master_config()]
            elif skill_data is not None:
                flags = [skill_data.get(str(m.get("FLG名", "")).strip(), 0) for m in self.get_master_config()]
            else:
                flags = [0 for m in self.get_master_config()]

            row_data = [target_civ_no, str_id, player_name, 0, 0, 0, 0] + flags
            
            if row_idx:
                range_str = f"A{row_idx}:{gspread.utils.rowcol_to_a1(row_idx, len(row_data))}"
                try:
                    # gspread 5.x までの記述
                    players_ws.update(range_str, [row_data])
                except TypeError:
                    # gspread 6.0 以降の記述 (引数の順番が逆になっているため例外で吸収)
                    players_ws.update([row_data], range_str)
            else:
                players_ws.append_row(row_data)
                
            logger.info(f"[SUCCESS] プレイヤーデータを保存しました: {player_name}")
            return True
        except Exception as e:
            logger.error(f"[ERROR] プレイヤーデータの保存に失敗しました: {e}")
            return False

    def _ensure_match_log_sheet(self, map_names: list) -> gspread.Worksheet:
        try:
            ws = self.sheet.worksheet("対戦ログ")
        except gspread.exceptions.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title="対戦ログ", rows="100", cols="20")
        current_headers = ws.row_values(1)
        base_headers = ["対戦ID", "実行日時", "募集ホストID", "採用マップ", "参加人数", "総投票数"]
        if not current_headers:
            ws.update("A1", [base_headers + map_names])
            return ws
        headers = current_headers.copy()
        for m_name in map_names:
            if m_name not in headers:
                headers.append(m_name)
        if len(headers) > len(current_headers):
            ws.update("A1", [headers])
        return ws

    def record_match_log(self, match_data: dict, map_names: list) -> bool:
        try:
            ws = self._ensure_match_log_sheet(map_names)
            row_data = [match_data.get(h, "") if h in ["対戦ID", "実行日時", "採用マップ"] else str(match_data.get("host_id", "")) if h == "募集ホストID" else match_data.get(h, 0) if h in ["参加人数", "総投票数"] else match_data.get("map_votes", {}).get(h, 0) if h in map_names else "" for h in ws.row_values(1)]
            ws.append_row(row_data)
            return True
        except Exception as e:
            logger.error(f"[ERROR] 対戦ログの記録失敗: {e}")
            return False
import itertools
import random

def balance_teams(players_info: dict) -> tuple[list, list]:
    """
    参加プレイヤーを2チームに分け、チームの合計スコア差が最小になる組み合わせ（全探索）を返す。
    
    Args:
        players_info (dict): {discord_id: {"name": str, "score": int}} の形式のデータ
        
    Returns:
        tuple[list, list]: チームAのIDリスト, チームBのIDリスト
    """
    p_ids = list(players_info.keys())
    n = len(p_ids)
    
    # 人数が1人以下の場合は分けられないのでそのまま返す
    if n < 2:
        return p_ids, []
        
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

def calculate_map_votes(map_votes_data: dict, participants: dict, map_emojis: dict) -> tuple[str, int]:
    """
    シークレット投票のデータを集計し、最も得票数の多いマップを決定する。
    """
    map_vote_counts = {name: 0 for name in map_emojis.keys()}
    
    # 現在の参加者リストに残っている人の投票だけを集計
    for p_id in participants.keys():
        if p_id in map_votes_data:
            voted_map = map_votes_data[p_id]
            if voted_map in map_vote_counts:
                map_vote_counts[voted_map] += 1

    if map_vote_counts and max(map_vote_counts.values()) > 0:
        max_vote_val = max(map_vote_counts.values())
        voted_maps = [k for k, v in map_vote_counts.items() if v == max_vote_val]
        chosen_map = random.choice(voted_maps)
    else:
        chosen_map = "未投票（ランダム等）"
        max_vote_val = 0
        
    return chosen_map, max_vote_val
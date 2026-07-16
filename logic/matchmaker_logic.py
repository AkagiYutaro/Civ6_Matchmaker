import itertools

def balance_teams(players_info: dict) -> tuple[list, list]:
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
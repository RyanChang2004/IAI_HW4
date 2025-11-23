import os
import re
import sys
import json
import random
import logging
import argparse

import openai
import tiktoken

# --- 基礎工具函數 ---

logger = logging.getLogger(__name__)
# 日誌等級保持在 INFO，以確保 'I'm alive! Calling GPT...' 顯示
logging.basicConfig(
    format="%(asctime)s - %(funcName)s() - %(message)s",
    datefmt="%Y/%m/%d %H:%M:%S",
    level=logging.INFO,
)

def read_txt(file):
    with open(file, "r", encoding="utf8") as f:
        return f.read()

def write_txt(file, text):
    with open(file, "w", encoding="utf8") as f:
        f.write(text)

def read_json(file):
    with open(file, "r", encoding="utf8") as f:
        return json.load(f)

def write_json(file, data, indent=None):
    with open(file, "w", encoding="utf8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)

class Config:
    def __init__(self, config_file):
        data = read_json(config_file)
        self.model = data["model"]
        self.static_dir = os.path.join(*data["static_dir"])
        self.state_dir = os.path.join(*data["state_dir"])
        self.output_dir = os.path.join(*data["output_dir"])
        os.makedirs(self.state_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        return

class GPT:
    def __init__(self, model):
        self.model = model
        self.tokenizer = tiktoken.encoding_for_model(self.model)
        self.model_candidate_tokens = {
            "gpt-3.5-turbo": {"gpt-3.5-turbo": 4096, "gpt-3.5-turbo-16k": 16384},
            "gpt-4": {"gpt-4": 8192, "gpt-4-32k": 32768}
        }
        return

    def get_specific_tokens_model(self, text_in, out_tokens):
        in_token_list = self.tokenizer.encode(text_in)
        in_tokens = len(in_token_list)
        tokens = in_tokens + out_tokens

        base_model_name = self.model.split('-')[0] + '-' + self.model.split('-')[1]

        for candidate, max_tokens in self.model_candidate_tokens.get(base_model_name, {}).items():
            if max_tokens >= tokens:
                break
        else:
            candidate = ""

        return in_tokens, candidate

    def run_gpt(self, text_in, out_tokens):
        in_tokens, specific_tokens_model = self.get_specific_tokens_model(text_in, out_tokens)
        if not specific_tokens_model:
            # 移除 'No suitable model found for token count.' 的日誌輸出
            return ""

        # 保留此 INFO 訊息
        logger.info("I'm alive! Calling GPT...")

        completion = openai.ChatCompletion.create(
            model=specific_tokens_model,
            n=1,
            messages=[{"role": "user", "content": text_in}]
        )

        text_out = completion.choices[0].message.content
        return text_out


# --- 核心狀態 (State) 類 ---

class State:
    def __init__(self, save_file=""):
        self.save_file = save_file

        self.game_log = ""
        self.player_name = "探險家"   # 玩家名稱
        self.save_title = "未命名旅程"  # 存檔標題
        self.current_location = "安全營地"
        self.ended = False

        # 核心戰鬥屬性
        self.player_stats = {
            "Attack": 0,    # 攻擊
            "Defense": 0,   # 防禦
            "HP": 0,        # 血量 (作為最大HP)
            "Luck": 0       # 運氣
        }
        self.current_hp = 0     # 當前血量

        # 遊戲進度
        self.chapter = 1            # Current game chapter (1, 2, 3)
        self.current_xp = 0         # Experience points
        self.xp_to_upgrade = 1      # 1 XP = 1 point
        self.resurrection_count = 0 # 新增：重生次數

        # 戰鬥臨時狀態
        self.combat_active = False
        self.enemy_name = ""
        self.enemy_stats = {}   # 包含 Attack/Defense/HP/XP_Reward
        self.enemy_current_hp = 0
        self.battle_log = ""
        return

    def save(self):
        data = {
            "game_log": self.game_log,
            "player_name": self.player_name,
            "save_title": self.save_title,
            "current_location": self.current_location,
            "ended": self.ended,
            "player_stats": self.player_stats,
            "current_hp": self.current_hp,
            "chapter": self.chapter,
            "current_xp": self.current_xp,
            "xp_to_upgrade": self.xp_to_upgrade,
            "resurrection_count": self.resurrection_count, # 儲存重生次數
        }
        write_json(self.save_file, data, indent=2)
        # 移除儲存日誌的輸出
        # logger.info(f"遊戲進度已儲存至 {self.save_file}")
        return

    def load(self):
        data = read_json(self.save_file)
        self.game_log = data.get("game_log", "")
        self.player_name = data.get("player_name", "探險家")
        self.save_title = data.get("save_title", "未命名旅程")
        self.current_location = data.get("current_location", "安全營地")
        self.ended = data.get("ended", False)
        self.player_stats = data.get("player_stats", {"Attack": 0, "Defense": 0, "HP": 0, "Luck": 0})
        self.current_hp = data.get("current_hp", 0)
        self.chapter = data.get("chapter", 1)
        self.current_xp = data.get("current_xp", 0)
        self.xp_to_upgrade = data.get("xp_to_upgrade", 1)
        self.resurrection_count = data.get("resurrection_count", 0) # 載入重生次數
        # 移除載入日誌的輸出
        # logger.info(f"遊戲進度已從 {self.save_file} 載入")
        return


# --- 遊戲主邏輯 (Game) 類 ---

class Game:
    def __init__(self, config):
        self.static_dir = config.static_dir
        self.state_dir = config.state_dir
        self.output_dir = config.output_dir
        self.summary_file = ""
        self.gpt = GPT(config.model)
        self.gpt4 = GPT("gpt-4") # 用於結局描寫

        self.user_prompt_to_text = {}
        self.max_saves = 4
        self.state = State()

        # 怪物數據定義 (Boss 1/2/3)
        self.BOSS_DATA = {
            1: {"name": "扭曲遊蕩者", "Attack": 20, "Defense": 25, "HP": 40, "XP_Reward": 100},
            2: {"name": "深淵領主", "Attack": 30, "Defense": 35, "HP": 60, "XP_Reward": 200},
            3: {"name": "【最終守護者】巨型混沌體", "Attack": 40, "Defense": 45, "HP": 80, "XP_Reward": 400},
        }

        # 小怪數據定義 (每章 3 種，隨機抽取)
        self.MOB_DATA_CHAPTER = {
            1: [
                {"name": "腐朽守衛", "Attack": 10, "Defense": 10, "HP": 15, "XP_Reward": 20},
                {"name": "迷失幽靈", "Attack": 11, "Defense": 9, "HP": 16, "XP_Reward": 22},
                {"name": "沉睡的藤蔓", "Attack": 9, "Defense": 12, "HP": 18, "XP_Reward": 25},
            ],
            2: [
                {"name": "荒野食腐獸", "Attack": 15, "Defense": 15, "HP": 25, "XP_Reward": 35},
                {"name": "黑暗低語者", "Attack": 17, "Defense": 14, "HP": 22, "XP_Reward": 40},
                {"name": "遠古守衛石像", "Attack": 14, "Defense": 18, "HP": 30, "XP_Reward": 45},
            ],
            3: [
                {"name": "深淵之眼", "Attack": 20, "Defense": 20, "HP": 35, "XP_Reward": 55},
                {"name": "虛空蠕蟲", "Attack": 22, "Defense": 19, "HP": 32, "XP_Reward": 60},
                {"name": "終末先驅", "Attack": 21, "Defense": 23, "HP": 40, "XP_Reward": 65},
            ],
        }

        # 載入 prompt text
        user_prompt_dir = os.path.join(self.static_dir, "user_prompt")
        if os.path.exists(user_prompt_dir):
            filename_list = os.listdir(user_prompt_dir)
            for filename in filename_list:
                if filename.endswith(".txt"):
                    user_prompt = filename[:-4]
                    user_prompt_file = os.path.join(user_prompt_dir, filename)
                    self.user_prompt_to_text[user_prompt] = read_txt(user_prompt_file)
        else:
            logger.warning(f"User prompt directory not found: {user_prompt_dir}")
        return

    # --- 啟動與存檔邏輯 ---

    def do_opening_story(self):
        """生成並顯示遊戲的背景故事。"""

        boss_names = [data['name'] for data in self.BOSS_DATA.values()]
        boss_list_str = "、".join(boss_names)

        gpt_in_story = (
            f"你是一位史詩探險的編劇家。請為這款遊戲撰寫一個簡短但引人入勝的背景故事。"
            f"故事需包含以下要素：\n"
            f"1. 玩家扮演一位探險家，從一個安全的營地出發。\n"
            f"2. 這片土地被三股強大的混沌力量所威脅，它們分別是：**{boss_list_str}**。故事必須提及這些名字，並暗示玩家必須按順序擊敗它們。\n"
            f"3. 玩家必須在野外磨練（打小怪）並提升自身能力，才能應對這些威脅。\n"
            f"請用 5 到 8 句話的篇幅，營造出一個充滿挑戰與希望的奇幻世界。無需開頭標題。"
        )

        print("\n" + "="*50)
        print("====== 📜 遊戲背景故事 (Opening Narrative) 📜 ======")
        print("="*50)

        story = self.gpt4.run_gpt(gpt_in_story, 800)
        print(story)
        print("="*50)

        self.state.game_log += f"\n--- 遊戲背景故事 ---\n{story}\n"
        input("\n(故事結束，按換行鍵開始你的旅程)... ")
        return

    def run_start(self):
        # get start type
        user_prompt = self.user_prompt_to_text.get("start", "1: 新旅程, 2: 載入存檔. 請選擇: ")
        while True:
            text_in = input(user_prompt)
            if text_in == "1":
                start_type = "new"
                break
            elif text_in == "2":
                start_type = "load"
                break

        save_list_text = "\n存檔列表：\n"
        saveid_to_exist = {}
        for i in range(self.max_saves):
            save_id = str(i + 1)
            save_file = os.path.join(self.state_dir, f"save_{save_id}.json")

            if os.path.exists(save_file):
                saveid_to_exist[save_id] = True

                # 讀取存檔標題、玩家名稱和進度
                try:
                    save_data = read_json(save_file)
                    title = save_data.get("save_title", "舊有旅程")
                    player_name = save_data.get("player_name", "探險家")
                    chapter = save_data.get("chapter", 1)
                    save_list_text += f"({save_id}) 📖 **{title}** (玩家: {player_name}, 第 {chapter} 章)\n"
                except:
                    save_list_text += f"({save_id}) ⚠️ **舊有存檔** (無法讀取)\n"

            else:
                saveid_to_exist[save_id] = False
                save_list_text += f"({save_id}) 空白存檔\n"

        user_prompt = f"{save_list_text}\n使用存檔欄位： "
        while True:
            text_in = input(user_prompt)
            if start_type == "new":
                if text_in in saveid_to_exist:
                    use_save_id = text_in
                    break
            else:
                if saveid_to_exist.get(text_in, False):
                    use_save_id = text_in
                    break

        self.summary_file = os.path.join(self.output_dir, f"summary_{use_save_id}.txt")
        use_save_file = os.path.join(self.state_dir, f"save_{use_save_id}.json")
        self.state = State(use_save_file)

        if start_type == "new":
            # 讓玩家為新的旅程取名
            title_input = input("請為你的旅程取一個名字 (如: '探索混沌'): ").strip()
            self.state.save_title = title_input or "未命名旅程"

            # 讓玩家為角色取名
            name_input = input("請為你的探險家取一個名字 (如: '阿爾法'): ").strip()
            self.state.player_name = name_input or "探險家"

            self.do_opening_story()
            self.state.save()
            self.do_game_start()
        else:
            self.state.load()
            self.do_game_start()

        return

    # --- 遊戲核心邏輯 ---

    def do_stat_allocation(self):
        """處理遊戲開始時的 75 點天賦值分配 (Attack, Defense, HP)，Luck 值隨機。"""

        # 3. Luck Rework: Set Luck randomly (1-100)
        luck_value = random.randint(1, 100)
        self.state.player_stats["Luck"] = luck_value

        # 3. Rework: Remaining points is 75 for Attack, Defense, HP
        total_points = 75
        stats = {"Attack": 0, "Defense": 0, "HP": 0}

        print("\n=== 天賦值分配：75 點 (初始天賦) ===")
        print("請分配以下三項屬性：攻擊、防禦、血量，總和不得超過 75 點。")
        print(f"🍀 運氣 (Luck) 已隨機設定為: {luck_value}")

        # Iterate only over Attack, Defense
        for stat_name in ["Attack", "Defense"]:
            while True:
                remaining = total_points - stats["Attack"] - stats["Defense"] - stats["HP"]
                try:
                    points = int(input(f"剩餘點數 {remaining} | {stat_name} (輸入分配點數): "))

                    if points < 0:
                        print("點數不能為負數。")
                    elif points > remaining:
                        print(f"分配點數 ({points}) 超出剩餘點數 ({remaining})。")
                    else:
                        stats[stat_name] = points
                        break
                except ValueError:
                    print("請輸入有效的數字。")

        # Handle HP allocation separately to enforce minimum 1 point
        while True:
            remaining = total_points - stats["Attack"] - stats["Defense"]
            try:
                hp_points = int(input(f"剩餘點數 {remaining} | HP (輸入分配點數): "))

                if hp_points < 0:
                    print("點數不能為負數。")
                elif hp_points > remaining:
                    print(f"分配點數 ({hp_points}) 超出剩餘點數 ({remaining})。")
                else:
                    # 2. HP Minimum: Set to 1 if 0 is allocated
                    if hp_points == 0:
                        print("⚠️ 血量 (HP) 分配點數不能為 0，已自動設定為 1 點。")
                        stats["HP"] = 1
                    else:
                        stats["HP"] = hp_points
                    break
            except ValueError:
                print("請輸入有效的數字。")


        # Finalize stats
        self.state.player_stats["Attack"] = stats["Attack"]
        self.state.player_stats["Defense"] = stats["Defense"]
        self.state.player_stats["HP"] = stats["HP"]
        self.state.current_hp = stats["HP"]

        # Calculate total points used for display
        total_used = stats["Attack"] + stats["Defense"] + stats["HP"]

        print("\n=== 屬性分配完成 ===")
        print(f"🔥 攻擊: {stats['Attack']}, 🛡️ 防禦: {stats['Defense']}, ❤️ 血量: {stats['HP']} | 總分配點數: {total_used}/{total_points}")
        print(f"🍀 運氣: {self.state.player_stats['Luck']} (隨機設定)")
        self.state.save()
        input("\n(按換行繼續)...")
        return

    # --- 戰鬥輔助函數 ---

    def _get_gpt_choice(self, prompt, valid_choices):
        """通用函數：讓 GPT 選擇 1/2/3 中的一個。"""
        try:
             choice_raw = self.gpt.run_gpt(prompt, 10).strip()
             match = re.search(r'\d', choice_raw)
             if match and match.group(0) in valid_choices:
                 return match.group(0)

             return random.choice(valid_choices)
        except Exception as e:
             # 移除 'GPT 選擇失敗' 的日誌輸出，因為函數已提供隨機選擇的備用方案
             return random.choice(valid_choices)

    def _calculate_damage(self, attacker_att, defender_def, hit_undefended):
        """根據統一規則計算傷害。"""
        if hit_undefended:
            # 攻擊成功 (命中未防守部位或運氣翻轉命中)：傷害 = 攻擊 - 防禦
            damage = max(1, attacker_att - defender_def)
            return damage
        else:
            # 攻擊失敗 (命中防守部位/被格擋)：傷害恆為 0。
            return 0

    def _calculate_upgrade_cost(self):
        """
        計算下一個能力點所需的 XP 成本 (動態調整)。
        成本 = 基礎成本 (Base Cost)
        """
        # 1. 計算總能力點數 (將 HP 轉換為點數，1 點 = 5 HP)
        # 這裡計算的是「有效」的總投入點數，包含隨機運氣值
        total_points = (
            self.state.player_stats["Attack"] +
            self.state.player_stats["Defense"] +
            # 雖然 HP 是點數分配，但這裡用於衡量總屬性強度，所以除以 5 來估算
            (self.state.player_stats["HP"] // 5) +
            (self.state.player_stats["Luck"] // 5) # 運氣也除以 5 算入總點數，避免過高的初始值造成極高成本
        )

        # 2. 基礎成本 (Base Cost) - 根據總點數遞增 (每 20 點增加 1 成本)
        # 例如: 0-19 點: 1, 20-39 點: 2, 40-59 點: 3...
        base_cost_multiplier = 1 + (total_points // 20)

        # 3. 最終成本 (Final Cost)
        final_cost = base_cost_multiplier

        return final_cost

    def _calculate_luck_probabilities(self):
        """計算好運和厄運的機率，最高 50%。"""

        # 0. L: Normalized Luck (0.01 to 1.0)
        # 確保 L 至少是 1
        L_val = max(1, self.state.player_stats["Luck"])
        L = L_val / 100.0

        # P_good: 好運機率 (將格擋/未命中變成命中/成功)
        # 隨著 L 增加而增加 (0.5% to 50%)
        P_good = L * 0.5

        # P_bad: 厄運機率 (將命中/成功變成格擋/失敗)
        # 隨著 L 增加而減少 (49.5% to 0%)
        P_bad = (1.0 - L) * 0.5

        return P_good, P_bad

    def do_upgrade_stats(self):
        """處理經驗值兌換能力值：成本隨能力值總和動態調整 (一次兌換一點)。運氣不能提升。"""

        while True:
            # 1. 計算當前兌換成本
            cost_per_point = self._calculate_upgrade_cost()

            print("\n=== 能力值兌換 ===")
            print(f"當前 XP: {self.state.current_xp} | 💰 **下一個點數成本: {cost_per_point} XP**")

            if self.state.current_xp < cost_per_point:
                print("經驗值不足，無法提升能力。")
                input("\n(按換行返回營地)...")
                break

            print("\n請選擇要提升的能力 (每次兌換一點):")
            print(f"(1) 攻擊 (Attack): {self.state.player_stats['Attack']} (+1 點)")
            print(f"(2) 防禦 (Defense): {self.state.player_stats['Defense']} (+1 點)")
            print(f"(3) 血量 (HP): {self.state.player_stats['HP']} (+1 HP/點)")
            print("(4) 返回營地")

            choice = input("輸入選項編號: ").strip()

            if choice == '4':
                self.state.save()
                break

            try:
                stat_index = int(choice)
                if stat_index not in [1, 2, 3]:
                    print("選項無效，請重新輸入。")
                    continue

                stat_map = {1: "Attack", 2: "Defense", 3: "HP"}
                stat_name = stat_map[stat_index]

                # 2. 執行兌換
                print(f"--- 兌換 {stat_name} 1 點，花費 {cost_per_point} XP ---")
                self.state.current_xp -= cost_per_point

                if stat_name == "HP":
                    stat_increase = 1
                    self.state.player_stats[stat_name] += stat_increase
                    self.state.current_hp += stat_increase
                    print(f"🎉 {stat_name} 提升 {stat_increase} 點，總值變為 {self.state.player_stats[stat_name]}。")
                else:
                    self.state.player_stats[stat_name] += 1
                    print(f"🎉 {stat_name} 提升 1 點，總值變為 {self.state.player_stats[stat_name]}。")

                self.state.save()

            except ValueError:
                print("輸入無效，請重新輸入。")
                continue
        return

    def do_reallocate_prompt(self):
        """詢問玩家是否重新分配當前能力點。"""
        # 計算總投入點數 (攻擊 + 防禦 + 血量)
        total_points_allocated = (
            self.state.player_stats["Attack"] +
            self.state.player_stats["Defense"] +
            self.state.player_stats["HP"]
        )

        print(f"\n[能力重新分配] 你從這次戰敗中學到了教訓。")
        print(f"你當前的總投入點數為: **{total_points_allocated}** (攻擊/防禦/血量)。")

        while True:
            choice = input("你想要重新分配這份總點數嗎？ (y/n): ").strip().lower()
            if choice == 'y':
                self.do_reallocate_stats(total_points_allocated)
                break
            elif choice == 'n':
                print("決定維持當前能力值。")
                break
            else:
                print("輸入無效，請輸入 'y' 或 'n'。")
        return

    def do_reallocate_stats(self, total_points):
        """處理戰敗後的重新分配能力值。"""

        stats = {"Attack": 0, "Defense": 0, "HP": 0}

        print("\n=== 重新分配能力值：三項總和必須等於 %s 點 ===" % total_points)
        print("請重新分配以下三項屬性：攻擊、防禦、血量。")
        print(f"🍀 運氣 (Luck) 維持不變: {self.state.player_stats['Luck']}")

        # 1. 分配 Attack 和 Defense
        for stat_name in ["Attack", "Defense"]:
            while True:
                # 剩餘點數是總點數減去已分配的 A, D, H
                remaining = total_points - stats["Attack"] - stats["Defense"] - stats["HP"]
                try:
                    points = int(input(f"剩餘點數 {remaining} | {stat_name} (輸入分配點數): "))

                    if points < 0:
                        print("點數不能為負數。")
                    elif points > remaining:
                        print(f"分配點數 ({points}) 超出剩餘點數 ({remaining})。")
                    else:
                        stats[stat_name] = points
                        break
                except ValueError:
                    print("請輸入有效的數字。")

        # 2. 強制分配 HP
        remaining_hp = total_points - stats["Attack"] - stats["Defense"]

        if remaining_hp <= 0:
            # HP 必須至少為 1 點。如果剩餘為 0，則必須從 A/D 拿走 1 點
            if remaining_hp == 0:
                if stats["Attack"] > 0:
                    stats["Attack"] -= 1
                    stats["HP"] = 1
                    print("⚠️ 由於你將所有點數分配給攻擊/防禦，系統自動從攻擊中移除 1 點，以確保 HP 至少為 1 點。")
                elif stats["Defense"] > 0:
                    stats["Defense"] -= 1
                    stats["HP"] = 1
                    print("⚠️ 由於你將所有點數分配給攻擊/防禦，系統自動從防禦中移除 1 點，以確保 HP 至少為 1 點。")
                else:
                    # 邊界情況：總點數只有 1 點，且 A/D 都沒選
                    stats["HP"] = 1
                    print("⚠️ 系統錯誤，HP 自動設定為 1。")
        else:
            # 正常情況：剩餘點數全給 HP
            stats["HP"] = remaining_hp

        # 3. Finalize stats
        self.state.player_stats["Attack"] = stats["Attack"]
        self.state.player_stats["Defense"] = stats["Defense"]
        self.state.player_stats["HP"] = stats["HP"]
        self.state.current_hp = stats["HP"] # 確保重新分配後滿血

        # Calculate total points used for display
        total_used = stats["Attack"] + stats["Defense"] + stats["HP"]

        print("\n=== 屬性重新分配完成 ===")
        print(f"🔥 攻擊: {stats['Attack']}, 🛡️ 防禦: {stats['Defense']}, ❤️ 血量: {stats['HP']} | 總分配點數: {total_used}")
        self.state.save()
        input("\n(按換行繼續)...")
        return

    # --- 回合制戰鬥邏輯 ---

    def do_player_phase(self):
        """玩家攻擊回合：玩家選擇攻擊部位，怪物選擇防禦部位。(包含逃跑選項)"""

        p_stats = self.state.player_stats
        e_stats = self.state.enemy_stats
        body_parts = {"1": "上部 (頭/角)", "2": "中部 (身體/核心)", "3": "下部 (腿/尾)"}

        # === 玩家選擇 / 狀態查看 / 逃跑 循環 ===
        player_attack_choice = ""

        while True:
            print(f"\n--- 你的回合 ---")
            print(f"🛡️ 你的 HP: {self.state.current_hp}/{self.state.player_stats['HP']} | 💀 {self.state.enemy_name} HP: {self.state.enemy_current_hp}/{e_stats['HP']}")

            action_choice = input("(1) 選擇攻擊部位 (2) 查看怪物屬性 (3) 逃跑回營地 | 請選擇行動：")

            if action_choice == "3":
                print("\n你嘗試逃跑...")

                # --- 運氣影響逃脫機率 ---
                luck = self.state.player_stats['Luck']

                # 逃跑成功率: 50% + (Luck - 50) / 200 (範圍約 25.5% 到 75%)
                escape_chance = 0.5 + ((luck - 50) / 200.0)

                print(f"🍀 你的運氣 ({luck}) 使逃跑成功率為 {escape_chance:.1%}。")

                if random.random() < escape_chance:
                    # 成功逃跑
                    print("🏃 成功！你抓住了機會逃脫了戰鬥，狼狽地回到了營地。")
                    self.state.combat_active = False # 結束戰鬥
                    self.state.save()
                    return # 退出 do_player_phase
                else:
                    # 逃跑失敗，結束玩家回合，進入怪物回合
                    print("❌ 失敗！怪物反應太快，你錯過了逃跑的時機。")
                    input("(按換行鍵結束你的回合)...")
                    return # 退出 do_player_phase，進入怪物回合


            elif action_choice == "2":
                print(f"\n=== 怪物屬性 ({self.state.enemy_name}) ===")
                print(f"攻擊力 (Attack): {e_stats['Attack']}, 防禦力 (Defense): {e_stats['Defense']}")
                print(f"生命值 (HP): {self.state.enemy_current_hp}/{e_stats['HP']}")
                continue

            elif action_choice == "1":
                player_attack_choice = input(f"選擇攻擊部位：(1){body_parts['1']} (2){body_parts['2']} (3){body_parts['3']} | 輸入編號：")
                if player_attack_choice in body_parts.keys():
                    break
                else:
                    print("攻擊部位選擇無效，請重新選擇。")
            else:
                print("輸入無效，請重新選擇。")

        player_attack_part = body_parts[player_attack_choice]


        # === 怪物防禦選擇 (GPT 操控) ===
        gpt_in_defense = (
            f"你是一位聰明的怪物AI。你正在與探險家戰鬥。你的屬性: 攻擊{e_stats['Attack']}, 防禦{e_stats['Defense']}。"
            f"探險家目前生命值 {self.state.current_hp}，你的生命值 {self.state.enemy_current_hp}。"
            f"請為{self.state.enemy_name}選擇一個新的防守部位，以避免被探險家擊中弱點。不要重複上回合的防禦部位。"
            f"只輸出一個數字 (1, 2 或 3)，無需解釋。"
        )
        enemy_defense_choice = self._get_gpt_choice(gpt_in_defense, list(body_parts.keys()))
        enemy_defense_part = body_parts[enemy_defense_choice]


        # === 傷害計算與判定 (我方攻擊) ===
        hit_undefended = (player_attack_choice != enemy_defense_choice)

        # --- 運氣值判定 (Luck Check) ---
        P_good, P_bad = self._calculate_luck_probabilities()
        damage_narration = ""
        is_luck_flip = False

        # 玩家攻擊回合：
        if hit_undefended: # 初始為命中 (玩家成功)
            # 判定厄運：將命中翻轉為格擋 (玩家的壞運)
            if random.random() < P_bad:
                hit_undefended = False
                is_luck_flip = True
                damage_narration = "😭 厄運降臨！你的攻擊在最後一刻被怪物完美格擋！"
        else: # 初始為格擋 (玩家失敗)
            # 判定好運：將格擋翻轉為命中 (玩家的好運)
            if random.random() < P_good:
                hit_undefended = True
                is_luck_flip = True
                damage_narration = "😲 好運爆棚！你的攻擊奇蹟般地穿透了怪物的防禦！"

        # 計算傷害
        player_damage_dealt = self._calculate_damage(
            p_stats["Attack"], e_stats["Defense"], hit_undefended
        )
        self.state.enemy_current_hp -= player_damage_dealt


        # === 戰鬥結果報告 ===
        if not is_luck_flip:
            if hit_undefended:
                attack_outcome_msg = "✅ 成功！攻擊命中怪物弱點！"
            else:
                attack_outcome_msg = "🚨 失敗！攻擊部位遭到精準防禦，傷害為 0！"
        else:
            attack_outcome_msg = damage_narration

        print("\n--- 你的回合：攻擊結果 ---")
        print(f"你的攻擊部位: {player_attack_part}")
        print(f"怪物防禦部位: {enemy_defense_part}")
        print(attack_outcome_msg)
        print(f"造成傷害: {player_damage_dealt}")
        print(f"怪物剩餘生命值: {max(0, self.state.enemy_current_hp)}")
        print("--------------------")

        # === GPT 描寫戰鬥結果 (敘事) ===
        gpt_in_narration = (
            f"你是一位說書人，請用生動的語言描寫這一回合的戰鬥。\n"
            f"探險家攻擊 {player_attack_part}，怪物防守 {enemy_defense_part}。"
            f"探險家造成 **{player_damage_dealt}** 傷害。"
            f"戰鬥結果：探險家HP {self.state.current_hp}，怪物HP {self.state.enemy_current_hp}。\n"
            f"請用 3 句話描述戰鬥過程，重點描寫攻擊和防禦的視覺效果。"
        )

        battle_narration = self.gpt.run_gpt(gpt_in_narration, 300)
        self.state.battle_log += f"[玩家回合] {battle_narration}\n"
        print(f"\n{battle_narration}\n")

        # 檢查戰鬥是否結束
        if self.state.enemy_current_hp <= 0:
            self.state.combat_active = False

        self.state.save()
        return

    def do_enemy_phase(self):
        """怪物攻擊回合：玩家選擇防禦部位，怪物選擇攻擊部位。"""

        p_stats = self.state.player_stats
        e_stats = self.state.enemy_stats
        body_parts = {"1": "上部 (頭/角)", "2": "中部 (身體/核心)", "3": "下部 (腿/尾)"}

        print(f"\n--- 怪物回合 ---")
        print(f"🛡️ 你的 HP: {self.state.current_hp}/{self.state.player_stats['HP']} | 💀 {self.state.enemy_name} HP: {self.state.enemy_current_hp}/{e_stats['HP']}")

        # === 玩家防禦選擇 ===
        player_defense_choice = ""
        while player_defense_choice not in body_parts.keys():
            player_defense_choice = input(f"選擇防禦部位：(1){body_parts['1']} (2){body_parts['2']} (3){body_parts['3']} | 輸入編號：")
        player_defense_part = body_parts[player_defense_choice]


        # === 怪物攻擊選擇 (GPT 操控) ===
        gpt_in_attack = (
            f"你是一位聰明的怪物AI。你正在攻擊探險家。你的攻擊力{e_stats['Attack']}。"
            f"探險家生命值 {self.state.current_hp}。"
            f"請為{self.state.enemy_name}選擇一個新的攻擊部位，以避免被探險家防禦。不要重複上回合的攻擊部位。"
            f"只輸出一個數字 (1, 2 或 3)，無需解釋。"
        )
        enemy_attack_choice = self._get_gpt_choice(gpt_in_attack, list(body_parts.keys()))
        enemy_attack_part = body_parts[enemy_attack_choice]


        # === 傷害計算與判定 (敵方攻擊) ===
        # hit_undefended = True 意味著玩家沒有防禦到，會被命中
        hit_undefended = (enemy_attack_choice != player_defense_choice)

        # --- 運氣值判定 (Luck Check) ---
        P_good, P_bad = self._calculate_luck_probabilities()
        damage_narration = ""
        is_luck_flip = False

        # 怪物攻擊回合：
        if hit_undefended: # 初始為命中 (玩家失敗)
            # 判定好運：將命中翻轉為格擋/閃避 (玩家的好運)
            if random.random() < P_good:
                hit_undefended = False
                is_luck_flip = True
                damage_narration = "✨ 好運救了你！怪物的攻擊在最後一刻偏離了目標！"
        else: # 初始為格擋 (玩家成功)
            # 判定厄運：將格擋翻轉為命中 (玩家的厄運)
            if random.random() < P_bad:
                hit_undefended = True
                is_luck_flip = True
                damage_narration = "💥 厄運降臨！怪物奇蹟般地擊中你防禦的空隙！"

        # 計算傷害
        enemy_damage_dealt = self._calculate_damage(
            e_stats["Attack"], p_stats["Defense"], hit_undefended
        )
        self.state.current_hp -= enemy_damage_dealt


        # === 戰鬥結果報告 ===
        if not is_luck_flip:
            if hit_undefended:
                attack_outcome_msg = "🚨 防禦失敗！攻擊命中你的弱點！"
            else:
                attack_outcome_msg = "✅ 成功！你的防禦奏效，傷害為 0！"
        else:
            attack_outcome_msg = damage_narration

        print("\n--- 怪物回合：攻擊結果 ---")
        print(f"怪物攻擊部位: {enemy_attack_part}")
        print(f"你的防禦部位: {player_defense_part}")
        print(attack_outcome_msg)
        print(f"受到傷害: {enemy_damage_dealt}")
        print(f"你的剩餘生命值: {max(0, self.state.current_hp)}")
        print("--------------------")

        # === GPT 描寫戰鬥結果 (敘事) ---
        gpt_in_narration = (
            f"你是一位說書人，請用生動的語言描寫怪物這一回合的攻擊。\n"
            f"怪物攻擊 {enemy_attack_part}，探險家防守 {player_defense_part}。"
            f"探險家受到 **{enemy_damage_dealt}** 傷害。"
            f"戰鬥結果：探險家HP {self.state.current_hp}，怪物HP {self.state.enemy_current_hp}。\n"
            f"請用 3 句話描述戰鬥過程，重點描寫攻擊和防禦的視覺效果。"
        )

        battle_narration = self.gpt.run_gpt(gpt_in_narration, 300)
        self.state.battle_log += f"[怪物回合] {battle_narration}\n"
        print(f"\n{battle_narration}\n")

        # 檢查戰鬥是否結束
        if self.state.current_hp <= 0:
            self.state.combat_active = False

        self.state.save()
        return

    # --- 遊戲流程控制函數 ---

    def do_game_start(self):
        """遊戲的啟動與流程控制：從營地開始。"""

        # 初始狀態檢查: 如果 HP 和 Luck 都是 0，則視為新分配
        if self.state.player_stats["HP"] == 0 and self.state.player_stats["Luck"] == 0:
            self.do_stat_allocation()

        self.do_camp_menu()

        return

    def _reset_game_state(self):
        """Reset player state for a new journey."""
        # Use the same save file, but reinitialize the state object
        save_file = self.state.save_file
        self.state = State(save_file)

        # Ask for a new title
        new_title = input("請為新的旅程取一個名字: ").strip()
        self.state.save_title = new_title or "未命名旅程"

        # Ask for a new name
        new_name = input("輸入你的新探險家名稱: ").strip()
        self.state.player_name = new_name or "探險家"

        self.state.save()
        print("\n--- 遊戲狀態已重置。歡迎來到新的旅程！---")

        # Since state is reset, go back to allocation
        self.do_stat_allocation()
        return

    def do_post_game_menu(self):
        """Handles the menu after defeating the final boss (Chapter 3)."""

        if not self.state.ended:
            print("\n\n" + "#"*50)
            print("######### 🏆 混沌已平息 - 旅程的終點 🏆 #########")
            print("#"*50)

            # 顯示最終勝利故事 (只執行一次)
            gpt_in_final_win = (
                f"你是一位史詩小說的作者。探險家以 HP:{self.state.current_hp} 的狀態擊敗了終極混沌，請描寫一個宏大、振奮人心的最終結局。主角的最終屬性：攻擊{self.state.player_stats['Attack']}, 防禦{self.state.player_stats['Defense']}。"
                f"描述探險家如何為這片土地帶來和平或獲得無上寶藏。"
            )
            final_story = self.gpt4.run_gpt(gpt_in_final_win, 600)
            print(final_story)

            self.state.game_log += f"\n--- 最終勝利結局 ---\n{final_story}"
            self.state.ended = True # Mark as completed
            self.state.save()
        else:
            print("\n你已經平息了所有混沌。這片土地再次和平。")

        # 提供新旅程選項
        while True:
            choice = input("\n請選擇下一步行動: (1) 開始新的旅程 (重置進度) (2) 結束遊戲 | 輸入編號: ")
            if choice == '1':
                self._reset_game_state()
                # Return from this function will lead back to do_camp_menu
                return
            elif choice == '2':
                print("遊戲結束。")
                self.state.ended = True
                return
            else:
                print("輸入無效。")

        return

    def do_camp_menu(self):
        """營地菜單：允許玩家準備或挑戰。"""

        if self.state.ended and self.state.chapter > 3:
            # 遊戲已結束（擊敗最終 Boss），直接進入結尾菜單
            self.do_post_game_menu()
            return

        if self.state.ended:
            # 玩家在 post-game menu 選擇退出
            return


        # 返回營地時自動回血
        if self.state.current_hp < self.state.player_stats["HP"]:
            print("💖 在安全營地休息，你的生命值恢復至最大！")
            self.state.current_hp = self.state.player_stats["HP"]
            self.state.save()

        # 顯示下一個點數的成本
        next_cost = self._calculate_upgrade_cost()

        print("\n" + "="*40)
        print(f"======== 🏡 營地 (探險家: {self.state.player_name} | 旅程: {self.state.save_title}) 🏡 ========")
        print("="*40)
        # 顯示重生次數
        print(f"🔥 力量: {self.state.player_stats['Attack']} | 🛡️ 防禦: {self.state.player_stats['Defense']} | ❤️ HP: {self.state.current_hp}/{self.state.player_stats['HP']} | 🍀 運氣: {self.state.player_stats['Luck']} | 🔄 重生次數: {self.state.resurrection_count}")

        while True:
            if self.state.chapter > 3:
                self.do_post_game_menu()
                return

            current_boss_name = self.BOSS_DATA[self.state.chapter]['name']

            print(f"\n--- 第 {self.state.chapter} 章 ---")

            # 顯示 XP 餘額和下一個點數的動態成本
            print(f"經驗值 (XP): {self.state.current_xp} | 下一個能力點成本: {next_cost} XP")

            # 移除動態成本標籤
            action = input(f"\n請選擇行動: (1) 挑戰 Boss ({current_boss_name}) (2) 進入小怪戰鬥 (3) 兌換能力值 (4) 退出遊戲 | 輸入編號: ")

            if action == '1':
                self.do_encounter(is_boss=True)
                if self.state.combat_active:
                    self.run_combat_loop()
                return
            elif action == '2':
                self.do_encounter(is_boss=False)
                if self.state.combat_active:
                    self.run_combat_loop()
                return
            elif action == '3':
                self.do_upgrade_stats()
                # 升級後重新計算下次成本
                next_cost = self._calculate_upgrade_cost()
            elif action == '4':
                print("遊戲結束。")
                self.state.ended = True
                return
            else:
                print("輸入無效。")

        return

    def run_combat_loop(self):
        """戰鬥循環，直到一方HP歸零或逃跑。"""
        while self.state.combat_active:

            # 1. 玩家回合 (do_player_phase 內部包含逃跑選項)
            self.do_player_phase()

            if not self.state.combat_active:
                # 戰鬥結束 (逃跑或玩家勝利)
                if self.state.enemy_current_hp <= 0:
                    # 判斷是否為 Boss 戰，以便決定是否推進章節
                    is_boss_fight = self.state.enemy_name in [data['name'] for data in self.BOSS_DATA.values()]
                    self.do_ending(is_boss_fight=is_boss_fight)
                else:
                    # 逃跑 (怪物HP > 0)
                    self.do_camp_menu()
                break

            input("\n(你的回合結束，按換行鍵進入怪物回合)...")

            # 2. 怪物回合
            self.do_enemy_phase()

            if not self.state.combat_active:
                # 戰鬥結束 (玩家死亡)
                is_boss_fight = self.state.enemy_name in [data['name'] for data in self.BOSS_DATA.values()]
                self.do_ending(is_boss_fight=is_boss_fight)
                break

            input("\n(怪物回合結束，按換行繼續下一回合)...")

        return

    # --- 戰鬥遭遇與結局 ---

    def do_encounter(self, is_boss):
        """設定 Boss 戰或小怪戰情境並設定敵人屬性。"""

        if is_boss:
            enemy_data = self.BOSS_DATA.get(self.state.chapter)
            if not enemy_data:
                print("錯誤：找不到當前章節的 Boss 數據！")
                self.state.combat_active = False
                return
            enemy_type_desc = "Boss"
        else:
            # 從當前章節的小怪列表中隨機選擇一個
            mob_list = self.MOB_DATA_CHAPTER.get(self.state.chapter)
            if not mob_list:
                print("錯誤：找不到當前章節的小怪數據！")
                self.state.combat_active = False
                return
            enemy_data = random.choice(mob_list)
            enemy_type_desc = "小怪"


        self.state.enemy_name = enemy_data["name"]
        self.state.enemy_stats = enemy_data
        self.state.enemy_current_hp = enemy_data["HP"]
        # **HP 狀態保留**
        self.state.combat_active = True

        gpt_in_scenario = (
            f"你是一位史詩探險的說書人。請描寫探險家與 {enemy_data['name']} 的遭遇情境。"
            f"地點：第 {self.state.chapter} 章的未知區域。"
            f"探險家屬性：攻擊{self.state.player_stats['Attack']}, 防禦{self.state.player_stats['Defense']}, 運氣{self.state.player_stats['Luck']}。"
            f"怪物屬性：攻擊{enemy_data['Attack']}, 防禦{enemy_data['Defense']}, 血量{enemy_data['HP']}。"
            f"描述應營造緊張氣氛，強調這是對抗{enemy_type_desc}的戰鬥。"
            f"總長度不超過 5 句話。"
        )

        encounter_narration = self.gpt.run_gpt(gpt_in_scenario, 400)
        self.state.game_log += f"\n--- 戰鬥遭遇：{enemy_data['name']} ---\n{encounter_narration}\n"

        print("\n" + "="*40)
        print(f"|  遭遇：{enemy_data['name']} (第 {self.state.chapter} 章 {enemy_type_desc})  |")
        print("="*40)
        print(encounter_narration)
        input("\n(戰鬥即將開始，按換行鍵進入)...")
        return

    def do_ending(self, is_boss_fight):
        """判斷戰鬥最終結果，並處理經驗值和章節進度。"""

        if self.state.current_hp > 0: # 玩家勝利

            if is_boss_fight:
                # Boss 勝利: 使用 GPT-4, 較長的敘事
                gpt_in_win = f"探險家以 HP:{self.state.current_hp} 的狀態擊敗了 {self.state.enemy_name}，請描寫一個短暫的勝利結局，強調探險家的英勇和獲得的戰利品。"
                ending_story = self.gpt4.run_gpt(gpt_in_win, 400)
            else:
                # 小怪勝利: 使用 GPT-3.5, 簡短的敘事 (1 句話)
                gpt_in_win = f"探險家擊敗了 {self.state.enemy_name}，請簡短描寫勝利，只需 1 句話，強調戰鬥的快速結束。"
                ending_story = self.gpt.run_gpt(gpt_in_win, 100)

            print("\n🎉 戰鬥勝利！ 🎉")
            print(ending_story)

            # 處理經驗值
            xp_reward = self.state.enemy_stats['XP_Reward']
            print(f"\n獲得經驗值: {xp_reward} XP")
            self.state.current_xp += xp_reward

            # 處理章節進度
            if is_boss_fight:
                self.state.chapter += 1
                if self.state.chapter <= 3:
                     print(f"🎉 成功開啟下一章：第 {self.state.chapter} 章！🎉")

        else: # 玩家失敗
            gpt_in_lose = f"探險家被 {self.state.enemy_name} 擊敗，請描寫一個帶有悲劇色彩的失敗結局，暗示挑戰者的命運。"
            ending_story = self.gpt4.run_gpt(gpt_in_lose, 400)
            print("\n💀 戰鬥失敗！你倒下了。 💀")
            print(ending_story)

            # --- 重生處理邏輯 (記錄和分配) ---
            self.state.resurrection_count += 1
            print(f"\n✨ 混沌的力量將你傳送回營地... 雖然你被打敗了，但你的靈魂在邊緣被拉回。")

            # 重生：回到滿血狀態
            self.state.current_hp = self.state.player_stats["HP"]
            print(f"🔄 重生次數: {self.state.resurrection_count} | 生命值恢復至 {self.state.current_hp}。")

            # 詢問是否重新分配點數
            self.do_reallocate_prompt()

        self.state.game_log += f"\n--- 戰鬥結束 ---\n{ending_story}"
        self.state.save()

        print("\n=== 流程回到營地。===")
        self.do_camp_menu()
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", type=str, default="lab2_config.json")
    arg = parser.parse_args()

    # 這裡要求輸入 API Key
    openai.api_key = input("OpenAI API Key: ")

    try:
        config = Config(arg.config_file)
        game = Game(config)
        game.run_start()
    except Exception as e:
        logger.error(f"遊戲運行發生錯誤: {e}")

    return

if __name__ == "__main__":
    main()
    sys.exit()
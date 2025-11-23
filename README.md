# IAI_HW4
# 📜 Game Report: Chaos Explorer - A Player's Guide 📜

This is a turn-based text adventure game where your goal is to enhance your abilities, engage in strategic combat, and ultimately defeat the three powerful Chaos Bosses.

## I. Attributes and Stats

Your Explorer possesses four core attributes that directly influence combat outcomes:

| Attribute | Effect Description | Notes |
| :-------: | :----------------- | :---- |
| **Attack** | Determines your base damage dealt to the enemy. | $Damage = \max(1, \text{Attack} - \text{Enemy Defense})$ |
| **Defense** | Reduces the base damage you take from enemies. | $Damage = \max(1, \text{Enemy Attack} - \text{Defense})$ |
| **HP** | Your maximum health points. Reaching zero results in defeat. | Upon defeat, you resurrect and heal to max HP. |
| **Luck** | Influences **random events** in combat and the **escape chance**. | Initial value is random (1-100), **cannot be upgraded with XP**. |

### Stat Allocation and Upgrades

* **Initial Allocation:** At the start, you allocate **75 points** across Attack, Defense, and HP (HP must be at least 1). Your Luck stat is set randomly.
* **Experience Points (XP):** Earned by defeating mobs and Bosses.
* **Upgrading Stats:** At the Camp menu, you can spend XP to increase Attack, Defense, or HP by 1 point. The XP cost for each upgrade **dynamically increases** based on your total allocated points.

## II. Game Flow and Combat Mechanics

### 1. The Camp (Safe Zone)

The Camp is your base of operations, offering the following:

* **Automatic Healing:** Your HP is restored to maximum upon returning.
* **Stat Upgrades:** Spend accumulated XP to improve your core stats.
* **Challenge Boss:** Take on the Boss of the current Chapter.
* **Mob Encounter:** Engage in random battles to farm XP.

### 2. Core Combat System

Combat is turn-based, alternating between the "Player Phase" and the "Enemy Phase." The core mechanic is a game of rock-paper-scissors based on body parts:

* **Body Parts:** (1) Upper (Head/Horn), (2) Middle (Body/Core), (3) Lower (Leg/Tail).

| Phase | Your Action | Opponent's Action (AI-driven) | Outcome Condition |
| :---: | :---------- | :---------------------------: | :---------------: |
| **Player** | **Choose Attack Part** | **Choose Defense Part** | Attack Part $\ne$ Defense Part $\rightarrow$ **Hit (Damage Dealt)** |
| **Enemy** | **Choose Defense Part** | **Choose Attack Part** | Defense Part $\ne$ Attack Part $\rightarrow$ **Hit (Damage Taken)** |

### 3. The Influence of Luck in Combat

Your Luck stat introduces random chance, potentially flipping the outcome of an attack or defense:

* **✨ Good Luck (P\_good):** Flips an action that would have failed (e.g., being blocked, taking damage) into a success (hit, dodge). **Higher Luck increases this chance (up to 50%).**
* **💥 Bad Luck (P\_bad):** Flips an action that would have succeeded (e.g., hitting the enemy, successful block) into a failure (blocked, hit). **Higher Luck decreases this chance.**

### 4. Escape Mechanism

During the Player Phase, you have the option to attempt an escape:

* **Escape Chance:** The success rate is influenced by your **Luck** stat.
    * The chance ranges from approximately **25.5% (Min Luck)** to **75% (Max Luck)**.
* **Result:**
    * **Success:** Combat ends, and you return to the Camp (HP state is preserved).
    * **Failure:** Your turn is consumed, and the battle proceeds immediately to the Enemy Phase.

### 5. Defeat and Resurrection

If your HP reaches zero:

* The Chaos force pulls you back to the Camp, and your **Resurrection Count increases by 1**.
* Your HP is fully restored to maximum.
* You will be prompted with the option to **reallocate** your total invested stat points (Attack + Defense + HP) based on what you learned from the defeat.

## III. Game Objective

The game is structured into three Chapters, each with a Boss you must defeat to advance:

1.  **Chapter 1:** Defeat **The Twisted Wanderer**
2.  **Chapter 2:** Defeat **The Abyssal Lord**
3.  **Chapter 3:** Defeat **[The Final Guardian] Gigantic Chaos Entity**

After defeating the final Boss, you achieve the ultimate victory and can choose to start a new journey.

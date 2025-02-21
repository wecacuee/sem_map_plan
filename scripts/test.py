import argparse

import numpy as np
import gymnasium as gym

import torch
from minigrid.core.constants import DIR_TO_VEC

from model import SemIRLModel
from expert_policy import shortest_path
import utils

def preprocess(grid_count, agent_pos, goal_pos):
    grid_count = torch.from_numpy(grid_count).float().cuda().unsqueeze(0).permute(0, 3, 1, 2)
    agent_pos = torch.from_numpy(agent_pos).cuda().unsqueeze(0)
    goal_pos = torch.from_numpy(goal_pos).cuda().unsqueeze(0)
    return grid_count, agent_pos, goal_pos

def get_next_pos(pos, action, width, height):
    assert (0 < pos[0] < width - 1) and (0 < pos[1] < height - 1)
    next_pos = np.clip(pos + DIR_TO_VEC[action], [1, 1], [width-2, height-2])
    return next_pos


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--grid_size', type=int, default=16, const=16, nargs='?',
        choices=[16, 64], help='Minigrid map size')
    args = parser.parse_args()

    env_name = f"MiniGrid-LavaLawnS{args.grid_size}-v0"
    env = gym.make(
        env_name,
        tile_size=32,
        render_mode="human",
        screen_size=640,
        highlight=False,
        use_lidar=True,
    )

    model = SemIRLModel(grid_size=args.grid_size, batch_size=1).cuda()
    model_path = f"./trained_models/{env_name}/model.pt"
    model.load_state_dict(torch.load(model_path))

    num_test = 100
    success, total = 0, 0
    expert_len, agent_len = 0, 0

    for i in range(num_test):
        obs, info = env.reset()

        # Expert path
        grid_map, goal = utils.extract_grid_map_and_goal(env.env.env.grid)
        pos = env.env.env.agent_pos
        width, height = grid_map.shape
        path = shortest_path(grid_map, pos, goal, include_goal=True)   

        states = np.array([p[0] for p in path])
        actions = np.array([p[1] for p in path])    

        # Continue if no shortest path found
        if len(states) == 0:
            print("No shortest path found, continue")
            continue
        if not (states[0] == env.agent_pos).all() or not (states[-1] == goal).all():
            print("No shortest path found, continue")
            continue

        agent_pos = states[0]
        goal_pos = states[-1]
        grid_count = np.zeros((width, height, 4), dtype=np.int32)

        # Maximum allowed agent path length is twice of the expert's
        for j in range(len(states) * 2):

            # Preprocess observations
            env.sem_lidar.set_pos(agent_pos)
            lidar_pts, lidar_labels = env.sem_lidar.detect()
            grid_count = utils.add_grid_counts(grid_count, lidar_pts, lidar_labels)

            data = preprocess(grid_count, agent_pos, goal_pos)
            logit, policy = model(*data)
            action = np.argmax(policy.squeeze().cpu().detach().numpy())

            agent_pos = get_next_pos(agent_pos, action, width, height)

            if (agent_pos == goal_pos).all():
                success += 1

                # Count agent and expert path length difference if they both succeed
                agent_len += j + 2
                expert_len += len(states)

                break

        total += 1

    print(f"Success: {success} / {total}")
    print(f"Agent successful paths total length is {agent_len}")
    print(f"In grids where agent succeeds, expert paths total length is {expert_len}")



if __name__ == '__main__':
    main()
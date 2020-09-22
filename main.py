# pylint: disable=no-member, invalid-name, not-callable, missing-docstring, line-too-long
import argparse
import os
import subprocess
from functools import partial

import torch

from bandit import grad_fn, init, master_matrix
from gradientflow import gradientflow_ode


def prob(f, arms, ss, s, a):
    # s = +1101
    # a = A0
    #ss = -1010
    if ss[1:] == s[2:] + a[1]:
        fa = f[arms.index(a[0])]
        return fa if ss[0] == '+' else 1 - fa
    return 0


def execute(args):
    torch.set_default_dtype(torch.float64)
    torch.manual_seed(args.seed)

    states, actions, arms, rewards = init(n_arms=args.arms, mem=args.memory)
    rewards = rewards.to(device=args.device)

    fs = torch.tensor([
        [0.5, 0.5 + args.gamma],
        [0.5, 0.5 - args.gamma],
        [0.5 + args.gamma, 0.5],
        [0.5 - args.gamma, 0.5],
    ])

    mms = [master_matrix(states, actions, partial(prob, f, arms)).to(device=args.device) for f in fs]

    w = torch.randn(len(states), len(actions)).mul(1).to(device=args.device)
    dynamics = []

    for state, internals in gradientflow_ode(w, partial(grad_fn, rewards, mms, args.eps), max_dgrad=args.max_dgrad):

        state['ngrad'] = internals['gradient'].norm().item()
        state['gain'] = internals['custom']
        dynamics.append(state)

        if state['step'] == args.step_stop:
            yield {
                'args': args,
                'dynamics': dynamics,
                'pi': internals['variables'].softmax(1),
            }
            return


def main():
    git = {
        'log': subprocess.getoutput('git log --format="%H" -n 1 -z'),
        'status': subprocess.getoutput('git status -z'),
    }

    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=str, default='cpu')

    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--memory", type=int, required=True)
    parser.add_argument("--arms", type=int, required=True)
    parser.add_argument("--gamma", type=float, default=0.1)

    parser.add_argument("--max_dgrad", type=float, default=1e-4)
    parser.add_argument("--eps", type=float, default=1e-8)
    parser.add_argument("--step_stop", type=int, default=1000)

    parser.add_argument("--pickle", type=str, required=True)
    args = parser.parse_args()

    torch.save(args, args.pickle)
    saved = False
    try:
        for res in execute(args):
            res['git'] = git
            with open(args.pickle, 'wb') as f:
                torch.save(args, f)
                torch.save(res, f)
                saved = True
    except:
        if not saved:
            os.remove(args.pickle)
        raise


if __name__ == "__main__":
    main()
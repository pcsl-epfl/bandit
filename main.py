# pylint: disable=no-member, invalid-name, not-callable, missing-docstring, line-too-long
import argparse
# import math
import os
import subprocess
from functools import partial
from time import perf_counter

import torch

from bandit import grad_fn, init, master_matrix
from gradientflow import gradientflow_ode


def optimize(args, w, mms, rewards, stop_steps):
    wall = perf_counter()
    wall_print = perf_counter()
    wall_save = perf_counter()

    dynamics = []

    for state, internals in gradientflow_ode(w, partial(grad_fn, rewards, mms, args.reset, args.eps), max_dgrad=args.max_dgrad):

        state['wall'] = perf_counter() - wall
        state['ngrad'] = internals['gradient'].norm().item()
        state['gain'] = internals['custom']
        dynamics.append(state)

        if perf_counter() - wall_print > 2:
            wall_print = perf_counter()
            print("wall={0[wall]:.0f} step={0[step]} t=({0[t]:.1e})+({0[dt]:.0e}) |dw|={0[ngrad]:.1e} G={0[gain]:.3f}".format(state), flush=True)

        save = False
        stop = False

        if perf_counter() - wall_save > 10:
            wall_save = perf_counter()
            save = True

        if state['step'] == stop_steps:
            save = True
            stop = True

        r = {
            'dynamics': dynamics,
            'weights': internals['variables'],
            'pi': internals['variables'].softmax(1),
        }

        if save:
            yield r

        if stop:
            return


def last(i):
    x = None
    for x in i:
        pass
    return x


def execute(args):
    torch.set_default_dtype(torch.float64)
    torch.manual_seed(args.seed)

    states, actions, arms, rewards, prob = init(n_arms=args.arms, mem=args.memory, mem_type=args.memory_type)
    rewards = rewards.to(device=args.device)

    assert args.arms == 2
    fs = torch.tensor([
        [0.5, 0.5 + args.gamma],
        [0.5, 0.5 - args.gamma],
        [0.5 + args.gamma, 0.5],
        [0.5 - args.gamma, 0.5],
    ])

    mms = [master_matrix(states, actions, partial(prob, f)).to(device=args.device) for f in fs]

    def w():
        return torch.randn(len(states), len(actions), device=args.device).mul(args.std0)

    rs = [last(optimize(args, w(), mms, rewards, args.trials_steps)) for _ in range(args.trials)]
    r = max(rs, key=lambda r: r['dynamics'][-1]['gain'])

    for r in optimize(args, r['weights'], mms, rewards, args.stop_steps):
        yield {
            'args': args,
            'states': states,
            'actions': actions,
            'arms': arms,
            'trials': rs,
            'main': r,
            'ram': None,
        }

    if args.bootstrap_ram == 1:
        if args.memory_type == 'shift':
            states2, actions2, arms2, rewards2, prob2 = init(n_arms=args.arms, mem=args.memory, mem_type='ram')
            assert states2 == states
            assert arms2 == arms

            mms2 = [master_matrix(states2, actions2, partial(prob2, f)).to(device=args.device) for f in fs]
            rewards2 = rewards2.to(device=args.device)

        w2 = torch.ones(len(states2), len(actions2)).mul(-100)
        for s, line in zip(states, r['weights']):
            for a, x in zip(actions, line):
                a = a[0] + s[2:] + a[1]
                w2[states2.index(s), actions2.index(a)] = x

        for r2 in optimize(args, w2, mms2, rewards2, args.stop_steps):
            yield {
                'args': args,
                'states': states,
                'actions': actions,
                'arms': arms,
                'trials': rs,
                'main': r,
                'ram': r2,
            }


def main():
    git = {
        'log': subprocess.getoutput('git log --format="%H" -n 1 -z'),
        'status': subprocess.getoutput('git status -z'),
    }

    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=str, default='cpu')

    parser.add_argument("--memory_type", type=str, required=True)
    parser.add_argument("--bootstrap_ram", type=int, default=0)
    parser.add_argument("--memory", type=int, required=True)
    parser.add_argument("--arms", type=int, default=2)
    parser.add_argument("--gamma", type=float, default=0.4)
    parser.add_argument("--reset", type=float, default=0.0)

    parser.add_argument("--seed", type=int, default=0)

    parser.add_argument("--bootstrap", type=str, default='none')
    parser.add_argument("--max_dgrad", type=float, default=1e-4)
    parser.add_argument("--eps", type=float, default=1e-8)
    parser.add_argument("--std0", type=float, default=1)

    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--trials_steps", type=int, default=0)

    parser.add_argument("--stop_steps", type=int, default=1000)
    # parser.add_argument("--stop_ngrad", type=float, default=0.0)

    parser.add_argument("--pickle", type=str, required=True)
    args = parser.parse_args()

    torch.save(args, args.pickle, _use_new_zipfile_serialization=False)
    saved = False
    try:
        for res in execute(args):
            res['git'] = git
            with open(args.pickle, 'wb') as f:
                torch.save(args, f, _use_new_zipfile_serialization=False)
                torch.save(res, f, _use_new_zipfile_serialization=False)
                saved = True
    except:
        if not saved:
            os.remove(args.pickle)
        raise


if __name__ == "__main__":
    main()

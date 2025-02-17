from abc import ABC, abstractmethod
import time
import os
import itertools as it
import numpy as np
import pandas as pd
import pickle as pk

from mlrose import get_short_name
from mlrose.runners.utils import build_data_filename


class _RunnerBase(ABC):

    @classmethod
    def runner_name(cls):
        return get_short_name(cls)

    def dynamic_runner_name(self):
        return self.__dynamic_short_name__ if hasattr(self, '__dynamic_short_name__') else self.runner_name()

    def _set_dynamic_runner_name(self, name):
        self.__dynamic_short_name__ = name

    @staticmethod
    def _print_banner(text):
        print('*' * len(text))
        print(text)
        print('*' * len(text))

    @abstractmethod
    def run(self):
        pass

    def __init__(self, problem, experiment_name, seed, iteration_list, max_attempts=500,
                 generate_curves=True, output_directory=None, **kwargs):
        self.problem = problem
        self.seed = seed
        self.iteration_list = iteration_list
        self.max_attempts = max_attempts
        self.generate_curves = generate_curves
        self.parameter_description_dict = {}

        self.run_stats_df = None
        self.curves_df = None
        self._raw_run_stats = []
        self._fitness_curves = []
        self._zero_curve_stat = None
        self._extra_args = kwargs
        self._output_directory = output_directory
        self._experiment_name = experiment_name
        self._current_logged_algorithm_args = {}
        self._run_start_time = None
        self._iteration_times = []

    def _setup(self):
        self._raw_run_stats = []
        self._fitness_curves = []
        self._iteration_times = []
        self._current_logged_algorithm_args.clear()
        if self._output_directory is not None:
            if not os.path.exists(self._output_directory):
                os.makedirs(self._output_directory)
        pass

    def _log_current_argument(self, arg_name, arg_value):
        self._current_logged_algorithm_args[arg_name] = arg_value

    def run_experiment_(self, algorithm, **kwargs):
        self._setup()
        # extract loop params
        values = [([(k, v) for v in vs]) for (k, (n, vs)) in kwargs.items() if vs is not None]
        self.parameter_description_dict = {k: n for (k, (n, vs)) in kwargs.items() if vs is not None}
        value_sets = list(it.product(*values))
        i = int(max(self.iteration_list))

        print(f'Running {self.dynamic_runner_name()}')
        run_start = time.perf_counter()
        for vns in value_sets:
            total_args = dict(vns)

            self._run_one_experiment(algorithm, i, total_args)

        run_end = time.perf_counter()
        print(f'Run time: {run_end - run_start}')

        self._create_and_save_run_data_frames()

        return self.run_stats_df, self.curves_df

    def _run_one_experiment(self, algorithm, max_iters, total_args, **kwargs):
        if self._extra_args is not None and len(self._extra_args) > 0:
            total_args.update(self._extra_args)
        user_info = [(k, v) for k, v in total_args.items()]
        self._invoke_algorithm(algorithm=algorithm, problem=self.problem, max_iters=max_iters,
                               max_attempts=self.max_attempts, curve=self.generate_curves,
                               user_info=user_info, **total_args)

    def _create_and_save_run_data_frames(self, extra_data_frames=None):
        self.run_stats_df = pd.DataFrame(self._raw_run_stats)
        self.curves_df = pd.DataFrame(self._fitness_curves)
        if self._output_directory is not None:
            self._dump_df_to_disk(self.run_stats_df, df_name='run_stats_df')
            if self.generate_curves:
                self._dump_df_to_disk(self.curves_df, df_name='curves_df')
            # output any extra
            if isinstance(extra_data_frames, dict):
                for n, v in extra_data_frames.items():
                    self._dump_df_to_disk(v, df_name=n)

    def _dump_df_to_disk(self, df, df_name):
        filename_root = self._dump_pickle_to_disk(object_to_pickle=df,
                                                  name=df_name)
        df.to_csv(f'{filename_root}.csv')
        print(f'Saving: [{filename_root}.csv]')

    def _dump_pickle_to_disk(self, object_to_pickle, name):
        if self._output_directory is None:
            return
        filename_root = build_data_filename(output_directory=self._output_directory,
                                            runner_name=self.dynamic_runner_name(),
                                            experiment_name=self._experiment_name,
                                            df_name=name)

        pk.dump(object_to_pickle, open(f'{filename_root}.p', "wb"))
        print(f'Saving: [{filename_root}.p]')
        return filename_root

    def _invoke_algorithm(self, algorithm, problem, max_attempts,
                          curve, user_info, additional_algorithm_args=None, **total_args):
        self._current_logged_algorithm_args.update(total_args)
        if additional_algorithm_args is not None:
            self._current_logged_algorithm_args.update(additional_algorithm_args)

        arg_text = [get_short_name(v) for v in self._current_logged_algorithm_args.values()]
        self._iteration_times.clear()
        self._print_banner(f'*** Run START - params: {arg_text}')
        np.random.seed(self.seed)
        self._run_start_time = time.perf_counter()
        ret = algorithm(problem=problem,
                        max_attempts=max_attempts,
                        curve=curve,
                        random_state=self.seed,
                        state_fitness_callback=self._save_state,
                        callback_user_info=user_info,
                        **total_args)
        print(f'*** Run END - params: {arg_text}')
        return ret

    @staticmethod
    def _create_curve_stat(iteration, fitness, curve_data, t=None):
        curve_stat = {
            'Iteration': iteration,
            'Time': t,
            'Fitness': fitness
        }
        curve_stat.update(curve_data)
        return curve_stat

    def _save_state(self, iteration, state, fitness, user_data, attempt=0, done=False, curve=None):

        # log iteration timing
        end = time.perf_counter()
        t = end - self._run_start_time
        self._iteration_times.append(t)

        # do we need to log anything else?
        if iteration > 0 and iteration not in self.iteration_list and not done:
            return True

        display_data = {**self._current_logged_algorithm_args}
        if user_data is not None and len(user_data) > 0:
            display_data.update({n: v for (n, v) in user_data})
            data_desc = ', '.join([f'{n}:[{get_short_name(v)}]' for n, v in display_data.items()])
            print(data_desc)
        print(f'runner_name:[{self.dynamic_runner_name()}], experiment_name:[{self._experiment_name}], ' +
              ('' if attempt is None else f'attempt:[{attempt}], ') +
              f'iteration:[{iteration}], done:[{done}], '
              f'time:[{t:.2f}], fitness:[{fitness:.4f}]')

        print(f'\t{state}'[120:])
        print()

        gd = lambda n: n if n not in self.parameter_description_dict.keys() else self.parameter_description_dict[n]

        param_stats = {str(gd(k)): get_short_name(v) for k, v in self._current_logged_algorithm_args.items()}

        # gather all stats
        current_iteration_stats = {**{p: v for (p, v) in user_data
                                      if p.lower() not in [k.lower() for k in param_stats.keys()]},
                                   **param_stats}

        # check for additional info
        gi = lambda k, v: {} if not hasattr(v, 'get_info__') else v.get_info__(t)
        ai = (gi(k, v) for k, v in self._current_logged_algorithm_args.items())
        additional_info = {k: v for d in ai for k, v in d.items()}

        if iteration > 0:
            remaining_iterations = [i for i in self.iteration_list if i >= iteration]
            iterations = [min(remaining_iterations)] if not done else remaining_iterations
        else:
            iterations = [0]

        for i in iterations:
            run_stat = {
                'Iteration': i,
                'Fitness': fitness,
                'Time': t,
                'State': state
            }
            run_stat = {**run_stat, **current_iteration_stats, **additional_info}

            self._raw_run_stats.append(run_stat)

        if self.generate_curves and iteration == 0:
            curve_stat = self._create_curve_stat(iteration=0,
                                                 fitness=fitness,
                                                 curve_data=current_iteration_stats,
                                                 t=t)
            self._zero_curve_stat = curve_stat

        if self.generate_curves and curve is not None and (done or iteration == max(self.iteration_list)):
            fc = list(zip(range(1, iteration + 1), curve))

            curve_stats = [self._zero_curve_stat] + [self._create_curve_stat(iteration=i,
                                                                             fitness=f,
                                                                             curve_data=current_iteration_stats,
                                                                             t=self._iteration_times[i])
                                                     for (i, f) in fc]
            self._fitness_curves.extend(curve_stats)

        return not done

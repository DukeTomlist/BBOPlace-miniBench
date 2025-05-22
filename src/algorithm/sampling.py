import numpy as np
from copy import deepcopy
from abc import abstractmethod
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
from pymoo.util.misc import calc_crowding_distance

import ray 
@ray.remote(num_cpus=1)
def evaluate_placer(placer, x0):
    return placer.evaluate(x0)

class BasicSampling():
    def __init__(self, args, evaluator, record_func) -> None:
        self.args = args
        self.evaluator = evaluator
        self.n_repeat = self.args.n_sampling_repeat

        self.record_func = record_func
    
    def do(self, n_samples):
        X, Y = None, None
        Y_all = None
        macro_pos_all = []
        for i in range(self.n_repeat):
            x, y, macro_pos = self._sampling_do(
                n_samples=n_samples,
            )
            if X is None and Y is None and Y_all is None:
                X = x
                Y = y
                Y_all = y
            else:
                X = np.concatenate([X, x], axis=0)
                Y = np.concatenate([Y, y], axis=0)
                Y_all = np.concatenate([Y_all, y], axis=0)
            macro_pos_all += macro_pos

            best_n_indices = np.argsort(Y)[:n_samples]
            X = X[best_n_indices]
            Y = Y[best_n_indices]
        
        if self.n_repeat > 1:
            self.record_func(
                hpwl=Y_all[np.argsort(Y_all)[n_samples:]], 
                macro_pos_all=list(np.array(macro_pos_all)[np.argsort(Y_all)[n_samples:]])
            ) 

        return X
    
    @abstractmethod
    def _sampling_do(self, n_samples, **kwargs):
        pass


class MOSampling(BasicSampling):
    def do(self, n_samples):
        X, Y_hpwl, Y_cong = None, None, None
        Y_hpwl_all, Y_cong_all = None, None
        macro_pos_all = []
        
        for i in range(self.n_repeat):
            x, y, macro_pos = self._sampling_do(n_samples=n_samples)
            
            if X is None:
                X = x
                Y_hpwl = y["hpwl"]
                Y_cong = y["congestion"]
                Y_hpwl_all = y["hpwl"]
                Y_cong_all = y["congestion"]
            else:
                X = np.concatenate([X, x], axis=0)
                Y_hpwl = np.concatenate([Y_hpwl, y["hpwl"]], axis=0)
                Y_cong = np.concatenate([Y_cong, y["congestion"]], axis=0)
                Y_hpwl_all = np.concatenate([Y_hpwl_all, y["hpwl"]], axis=0)
                Y_cong_all = np.concatenate([Y_cong_all, y["congestion"]], axis=0)
            
            macro_pos_all += macro_pos

            F = np.column_stack([Y_hpwl, Y_cong])
            
            nds = NonDominatedSorting()
            fronts = nds.do(F)
            
            selected_indices = []
            front_idx = 0
            
            while len(selected_indices) < n_samples and front_idx < len(fronts):
                current_front = fronts[front_idx]
                
                if len(selected_indices) + len(current_front) <= n_samples:
                    selected_indices.extend(current_front)
                else:
                    remaining = n_samples - len(selected_indices)
                    
                    crowding_dist = calc_crowding_distance(F[current_front])
                    
                    selected_from_front = current_front[np.argsort(-crowding_dist)[:remaining]]
                    selected_indices.extend(selected_from_front)
                
                front_idx += 1
                
            selected_indices = np.array(selected_indices)
            X = X[selected_indices]
            Y_hpwl = Y_hpwl[selected_indices]
            Y_cong = Y_cong[selected_indices]

        if self.n_repeat > 1:
            F_all = np.column_stack([Y_hpwl_all, Y_cong_all])
            fronts_all = nds.do(F_all)
            
            not_selected = []
            count = 0
            for front in fronts_all:
                for idx in front:
                    if count >= n_samples:
                        not_selected.append(idx)
                    count += 1
                    
            self.record_func(
                hpwl=Y_hpwl_all[not_selected],
                congestion=Y_cong_all[not_selected],
                macro_pos_all=list(np.array(macro_pos_all)[not_selected])
            )

        return X

###################################################################
#  Grid Guide sampling
###################################################################

class GGRandomSampling(BasicSampling):
    def __init__(self, args, evaluator, record_func) -> None:
        BasicSampling.__init__(self, args=args, evaluator=evaluator, record_func=record_func)

        self.xl = evaluator.xl
        self.xu = evaluator.xu
        self.n_dim = evaluator.n_dim
    
    def _sampling_do(self, n_samples):
        x = np.column_stack(
            [np.random.randint(self.xl[k], self.xu[k] + 1, size=n_samples) 
            for k in range(self.n_dim)]
        )
        y, macro_pos = self.evaluator.evaluate(x)

        return x, y, macro_pos
    
###################################################################
#  SP sampling
###################################################################

class SPRandomSampling(BasicSampling):
    def __init__(self, args, evaluator, record_func) -> None:
        BasicSampling.__init__(self, args=args, evaluator=evaluator, record_func=record_func)

        self.n_dim = evaluator.n_dim
    
    def _sampling_do(self, n_samples):
        x = self._permutation_sample(self, n_samples)
        y, macro_pos = self.evaluator.evaluate(x)
         
        return x, y, macro_pos

    def _permutation_sample(self, n_samples):
        X1 = self._get_permutation(n_samples=n_samples)
        X2 = self._get_permutation(n_samples=n_samples)
        X = np.concatenate([X1, X2], axis=1)
        return X
    
    def _get_permutation(self, n_samples):
        n_dim = self.n_dim // 2
        X = np.full((n_samples, n_dim), 0, dtype=int)
        for i in range(n_samples):
            X[i, :] = np.random.permutation(n_dim)
        return X
    
REGISTRY = {}
REGISTRY["gg"] = GGRandomSampling
REGISTRY["sp"] = SPRandomSampling
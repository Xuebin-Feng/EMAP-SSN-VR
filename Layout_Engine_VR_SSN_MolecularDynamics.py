import numpy as np
import math
from collections import deque

try:
    from numba import jit
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False

import sys
import os
# Allow importing from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import torch
    from utilities import Hardware_Utils
    HAS_TORCH = True
    print(f"PyTorch GPU support loaded successfully. CUDA Available: {torch.cuda.is_available()}")
except Exception as e:
    HAS_TORCH = False
    print(f"Failed to load PyTorch GPU support: {e}. Falling back to CPU.")

# --- 1. Physics Kernels ---

def _get_physics_kernel():
    def _run_physics_kernel(pos, vel, springs, comp_labels, box_limit, dt, damping, k_spr, k_coul, max_f, cutoff_dist):
        n_balls = pos.shape[0]
        acc = np.zeros_like(pos)
        
        # Calculate squared cutoff for efficient distance comparison
        cutoff_sq = cutoff_dist * cutoff_dist 
        
        # --- SPRINGS (Attraction) ---
        for i in range(springs.shape[0]):
            idx_a, idx_b = springs[i, 0], springs[i, 1]
            dx = pos[idx_a, 0] - pos[idx_b, 0]
            dy = pos[idx_a, 1] - pos[idx_b, 1]
            dz = pos[idx_a, 2] - pos[idx_b, 2]
            dist = math.sqrt(dx*dx + dy*dy + dz*dz) + 1e-9
            
            f = -k_spr * dist
            
            acc[idx_a, 0] += f * (dx/dist); acc[idx_a, 1] += f * (dy/dist); acc[idx_a, 2] += f * (dz/dist)
            acc[idx_b, 0] -= f * (dx/dist); acc[idx_b, 1] -= f * (dy/dist); acc[idx_b, 2] -= f * (dz/dist)
            
        # --- REPULSION (Coulomb Only) ---
        for i in range(n_balls):
            for j in range(i+1, n_balls):
                dx = pos[i, 0] - pos[j, 0]
                dy = pos[i, 1] - pos[j, 1]
                dz = pos[i, 2] - pos[j, 2]
                dist_sq = dx*dx + dy*dy + dz*dz
                
                if dist_sq > cutoff_sq: continue 
                if dist_sq == 0.0: continue 

                dist = math.sqrt(dist_sq)
                safe_dist = max(dist, 0.5) 
                
                f = k_coul / (safe_dist**2)
                
                if f > max_f: f = max_f
                
                acc[i, 0] += f*(dx/dist); acc[i, 1] += f*(dy/dist); acc[i, 2] += f*(dz/dist)
                acc[j, 0] -= f*(dx/dist); acc[j, 1] -= f*(dy/dist); acc[j, 2] -= f*(dz/dist)
                    
        # --- INTEGRATION (Euler) ---
        rmsd = 0.0
        for i in range(n_balls):
            acc[i] -= damping * vel[i]
            vel[i] += acc[i] * dt
            old_p = pos[i].copy()
            pos[i] += vel[i] * dt
            
            if pos[i,0] > box_limit: pos[i,0]=box_limit; vel[i,0]*=-0.5
            elif pos[i,0] < -box_limit: pos[i,0]=-box_limit; vel[i,0]*=-0.5
            if pos[i,1] > box_limit: pos[i,1]=box_limit; vel[i,1]*=-0.5
            elif pos[i,1] < -box_limit: pos[i,1]=-box_limit; vel[i,1]*=-0.5
            if pos[i,2] > box_limit: pos[i,2]=box_limit; vel[i,2]*=-0.5
            elif pos[i,2] < -box_limit: pos[i,2]=-box_limit; vel[i,2]*=-0.5
            
            diff = pos[i] - old_p
            rmsd += diff[0]**2 + diff[1]**2 + diff[2]**2
            
        return math.sqrt(rmsd / n_balls)
        
    if NUMBA_AVAILABLE:
        return jit(nopython=True, fastmath=True)(_run_physics_kernel)
    return _run_physics_kernel

run_physics_kernel = _get_physics_kernel()

class SSNSimulationCPU:
    def __init__(self, pos, springs, comp_labels, box_limit, params):
        self.pos = pos.astype(np.float32)
        self.vel = np.zeros_like(pos)
        self.springs = springs
        self.comp_labels = comp_labels
        self.box = box_limit
        self.params = params
        
    def step(self, current_step, apply_warmup=True):
        max_cutoff = self.params.get('COULOMB_CUTOFF', 15.0)
        max_steps = self.params.get('MAX_STEPS', 2000)
        
        if apply_warmup:
            target_step = max_steps / 4.0
            curve_scale = target_step / 5.0 
            
            if current_step >= target_step:
                cutoff = max_cutoff
            else:
                num = math.atan(current_step / curve_scale)
                den = math.atan(target_step / curve_scale)
                cutoff = max_cutoff * (num / den)
        else:
            cutoff = max_cutoff

        return run_physics_kernel(
            self.pos, self.vel, self.springs, self.comp_labels, self.box, 
            self.params.get('DT', 0.1), 
            self.params.get('DAMPING', 0.5), 
            self.params.get('SPRING_K', 0.1), 
            self.params.get('COULOMB_K', 50.0), 
            self.params.get('MAX_FORCE_LIMIT', 10.0), 
            cutoff 
        )
        
    def get_pos(self): return self.pos

if HAS_TORCH:
    class SSNSimulationGPU:
        def __init__(self, pos, springs, comp_labels, box_limit, params):
            self.device = Hardware_Utils.get_optimal_device()
            self.pos = torch.tensor(pos, dtype=torch.float32, device=self.device)
            self.vel = torch.zeros_like(self.pos)
            self.springs = torch.tensor(springs, dtype=torch.long, device=self.device)
            self.comp_labels = torch.tensor(comp_labels, dtype=torch.long, device=self.device)
            self.box = box_limit
            self.params = params
        
        @torch.no_grad()
        def step(self, current_step, apply_warmup=True):
            max_cutoff = self.params.get('COULOMB_CUTOFF', 15.0)
            max_steps = self.params.get('MAX_STEPS', 2000)
            
            if apply_warmup:
                target_step = max_steps / 4.0
                curve_scale = target_step / 5.0 
                
                if current_step >= target_step:
                    cutoff = max_cutoff
                else:
                    num = math.atan(current_step / curve_scale)
                    den = math.atan(target_step / curve_scale)
                    cutoff = max_cutoff * (num / den)
            else:
                cutoff = max_cutoff

            # --- PHYSICS ---
            delta = self.pos.unsqueeze(1) - self.pos.unsqueeze(0)
            dist = delta.norm(dim=2) + 1e-9
            
            # Element-wise force magnitude calculation
            f_mag = self.params.get('COULOMB_K', 50.0) / (dist.clamp(min=0.5)**2)
            
            # Zero out forces outside the cutoff or self-repulsion using torch.where
            is_self = torch.eye(dist.size(0), dtype=torch.bool, device=self.device)
            cond = (dist < cutoff) & (~is_self)
            f_mag = torch.where(cond, f_mag, 0.0)
            
            f_mag = f_mag.clamp(max=self.params.get('MAX_FORCE_LIMIT', 10.0))
            acc = (f_mag.unsqueeze(2) * (delta/dist.unsqueeze(2))).sum(dim=1)
            
            if len(self.springs) > 0:
                idx_a, idx_b = self.springs[:,0], self.springs[:,1]
                pa, pb = self.pos[idx_a], self.pos[idx_b]
                d = (pa-pb).norm(dim=1) + 1e-9
                f = -self.params.get('SPRING_K', 0.1) * d
                fv = f.unsqueeze(1) * ((pa-pb)/d.unsqueeze(1))
                acc.index_add_(0, idx_a, fv); acc.index_add_(0, idx_b, -fv)
                del pa, pb, d, f, fv
            
            damping = self.params.get('DAMPING', 0.5)
            dt = self.params.get('DT', 0.1)
            
            acc -= damping * self.vel
            self.vel += acc * dt
            old = self.pos.clone()
            self.pos += self.vel * dt
            
            # --- Boundary Collisions (Match CPU Bouncing) ---
            out_of_bounds_x = self.pos[:, 0].abs() > self.box
            out_of_bounds_y = self.pos[:, 1].abs() > self.box
            out_of_bounds_z = self.pos[:, 2].abs() > self.box
            
            # Reverse and dampen velocity for nodes hitting the walls
            self.vel[out_of_bounds_x, 0] *= -0.5
            self.vel[out_of_bounds_y, 1] *= -0.5
            self.vel[out_of_bounds_z, 2] *= -0.5
            
            # Clamp positions
            self.pos.clamp_(min=-self.box, max=self.box)
            
            rmsd = (self.pos - old).norm(dim=1).pow(2).mean().sqrt().item()
            
            del delta, dist, cond, is_self, f_mag, acc, old
            return rmsd

        def get_pos(self): return self.pos.cpu().numpy()

# --- 2. Components & Packing Logic ---

def find_connected_components(n_nodes, edges):
    """Finds all independent subgraphs using Breadth-First Search."""
    adj = {i: [] for i in range(n_nodes)}
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)
    
    visited = np.zeros(n_nodes, dtype=bool)
    components = []
    
    for i in range(n_nodes):
        if not visited[i]:
            comp = []
            q = [i]
            visited[i] = True
            while q:
                curr = q.pop(0)
                comp.append(curr)
                for neighbor in adj[curr]:
                    if not visited[neighbor]:
                        visited[neighbor] = True
                        q.append(neighbor)
            components.append(comp)
    return components

def get_component_labels(n_nodes, edges):
    """Maps each node to its connected component ID for isolated physics."""
    components = find_connected_components(n_nodes, edges)
    labels = np.zeros(n_nodes, dtype=np.int32)
    for c_id, comp in enumerate(components):
        for node in comp:
            labels[node] = c_id
    return labels

def pack_components_to_grid(pos, edges, n_nodes, grid_size, padding):
    """Packs independent network components into a 3D grid layout."""
    print("Packing independent components using 3D grid packing...")
    components = find_connected_components(n_nodes, edges)
    if not components:
        return pos, 100.0
        
    comp_info = []
    for c_id, comp in enumerate(components):
        idx = np.array(comp)
        comp_pos = pos[idx]
        
        # Center the component
        center = np.mean(comp_pos, axis=0)
        comp_pos -= center
        
        # Calculate bounding box radius
        radius = np.max(np.linalg.norm(comp_pos, axis=1)) + padding
        
        comp_info.append({
            'indices': idx,
            'pos': comp_pos,
            'radius': radius,
            'num_nodes': len(idx)
        })
        
    # Sort largest first
    comp_info.sort(key=lambda x: x['num_nodes'], reverse=True)
    
    # Simple 3D grid placement based on max radius
    if not comp_info: return pos, 100.0
    
    max_r = comp_info[0]['radius']
    step_size = max_r * 2
    
    n_comps = len(comp_info)
    grid_side = int(np.ceil(n_comps ** (1/3)))
    
    new_pos = np.zeros((n_nodes, 3), dtype=np.float32)
    new_pos[:] = pos[:]
    
    for idx, comp in enumerate(comp_info):
        layer = idx // (grid_side * grid_side)
        rem = idx % (grid_side * grid_side)
        row = rem // grid_side
        col = rem % grid_side
        
        offset = np.array([
            (col - grid_side/2.0) * step_size,
            (row - grid_side/2.0) * step_size,
            (layer - grid_side/2.0) * step_size
        ], dtype=np.float32)
        
        new_pos[comp['indices']] = comp['pos'] + offset
        
    global_min = np.min(new_pos, axis=0)
    global_max = np.max(new_pos, axis=0)
    center = (global_max + global_min) / 2.0
    new_pos -= center
    
    new_box_limit = np.max(global_max - global_min) / 2.0 * 1.1
    print(f"Packed {len(components)} objects into a 3D grid. Ready for display.")
    return new_pos, new_box_limit

# --- 3. Main Layout Algorithm ---

def calculate_layout(connectivity, n_nodes, params):
    """
    Main layout generation pipeline.
    
    connectivity: N x 3 NumPy array representing [Source_Index, Target_Index, Score]
    n_nodes: Total number of nodes in the network
    params: Dictionary containing physics and execution parameters
    
    Returns:
        pos (np.ndarray): Final X/Y coordinates
        box_limit (float): Boundary box size
    """
    
    edges = connectivity[:, :2].astype(np.int32)
    edge_scores = connectivity[:, 2]
    
    # Initialize basic 3D grid positioning to start
    side = int(np.ceil(n_nodes ** (1/3)))
    base_box = (n_nodes ** (1/3)) * 2.5 + 5.0
    initial_box_limit = base_box * params.get('BOX_SCALE', 1.0)
    x = np.linspace(-initial_box_limit*0.5, initial_box_limit*0.5, side)
    y = np.linspace(-initial_box_limit*0.5, initial_box_limit*0.5, side)
    z = np.linspace(-initial_box_limit*0.5, initial_box_limit*0.5, side)
    xv, yv, zv = np.meshgrid(x, y, z)
    initial_pos = np.column_stack((xv.flatten(), yv.flatten(), zv.flatten()))[:n_nodes].astype(np.float32)

    components = find_connected_components(n_nodes, edges)
    
    # 1. Sort components from largest to smallest
    components.sort(key=len, reverse=True)
    
    # 2. Skip single nodes completely
    active_comps = [c for c in components if len(c) > 1]
    singletons = len(components) - len(active_comps)
    
    large_comps = [c for c in active_comps if len(c) >= 500]
    small_comps = [c for c in active_comps if len(c) < 500]

    batches = []
    current_batch = []
    current_nodes = 0
    BATCH_LIMIT = 2000

    for comp in small_comps:
        if current_nodes + len(comp) > BATCH_LIMIT and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_nodes = 0
        current_batch.append(comp)
        current_nodes += len(comp)
    if current_batch:
        batches.append(current_batch)

    jobs = [[c] for c in large_comps] + batches
    
    print(f"Found {len(active_comps)} active components.")
    print(f"  > Simulating {len(large_comps)} massive components individually.")
    print(f"  > Grouped {len(small_comps)} small components into {len(batches)} parallel batches (Max {BATCH_LIMIT} nodes/batch).")
    print(f"  > Skipped {singletons} single nodes.")
    
    final_pos = np.copy(initial_pos)
    
    # Pre-map edges and scores to components for O(1) extraction
    node_to_comp_idx = {}
    for c_idx, comp in enumerate(active_comps):
        for node in comp:
            node_to_comp_idx[node] = c_idx
            
    comp_edges = {c_idx: [] for c_idx in range(len(active_comps))}
    comp_scores = {c_idx: [] for c_idx in range(len(active_comps))}
    
    for i, (u, v) in enumerate(edges):
        if u in node_to_comp_idx: 
            c_idx = node_to_comp_idx[u]
            comp_edges[c_idx].append((u, v))
            comp_scores[c_idx].append(edge_scores[i])
    
    # 3. Simulate jobs sequentially
    for job_idx, batch_comps in enumerate(jobs):
        n_batch_nodes = sum(len(c) for c in batch_comps)
        is_large_job = len(batch_comps) == 1 and n_batch_nodes >= 500

        # Build batch-level arrays
        batch_global_nodes = []
        for c in batch_comps:
            batch_global_nodes.extend(c)

        global_to_batch = {g_id: l_id for l_id, g_id in enumerate(batch_global_nodes)}

        batch_edges_list = []
        batch_scores_list = []
        batch_pos_list = []

        grid_side = int(np.ceil(len(batch_comps) ** (1/3)))
        spacing = 100.0

        # Construct initial positions per component
        for c_idx_in_batch, c in enumerate(batch_comps):
            n_comp_nodes = len(c)
            c_idx = node_to_comp_idx[c[0]]

            c_edges = comp_edges[c_idx]
            c_scores = comp_scores[c_idx]

            comp_global_to_local = {g: l for l, g in enumerate(c)}
            c_local_edges = [(comp_global_to_local[u], comp_global_to_local[v]) for u, v in c_edges]

            comp_box_limit = (n_comp_nodes ** (1/3) * 2.5 + 5.0) * params.get('BOX_SCALE', 1.0)
            local_pos = None
            spectral_success = False

            if n_comp_nodes >= 4:
                if n_comp_nodes >= 50:
                    print(f"  > Calculating Spectral Layout for sub-component ({n_comp_nodes} nodes)...")
                try:
                    import scipy.sparse as sp
                    from scipy.sparse.csgraph import laplacian
                    from scipy.sparse.linalg import eigsh

                    row = [e[0] for e in c_local_edges] + [e[1] for e in c_local_edges]
                    col = [e[1] for e in c_local_edges] + [e[0] for e in c_local_edges]
                    data = c_scores + c_scores
                    adj = sp.coo_matrix((data, (row, col)), shape=(n_comp_nodes, n_comp_nodes))

                    L = laplacian(adj, normed=True)
                    vals, vecs = eigsh(L, k=4, which='SM', tol=1e-3)

                    x_coords = vecs[:, 1]
                    y_coords = vecs[:, 2]
                    z_coords = vecs[:, 3]

                    x_norm = (x_coords - np.min(x_coords)) / (np.ptp(x_coords) + 1e-9)
                    y_norm = (y_coords - np.min(y_coords)) / (np.ptp(y_coords) + 1e-9)
                    z_norm = (z_coords - np.min(z_coords)) / (np.ptp(z_coords) + 1e-9)

                    x_scaled = (x_norm - 0.5) * comp_box_limit * 0.8
                    y_scaled = (y_norm - 0.5) * comp_box_limit * 0.8
                    z_scaled = (z_norm - 0.5) * comp_box_limit * 0.8

                    local_pos = np.column_stack((x_scaled, y_scaled, z_scaled)).astype(np.float32)
                    spectral_success = True
                except Exception as e:
                    if n_comp_nodes >= 50:
                        print(f"  > Spectral solver failed: {e}. Falling back to grid layout.")

            if not spectral_success:
                side_comp = int(np.ceil(n_comp_nodes ** (1/3)))
                x_c = np.linspace(-comp_box_limit * 0.5, comp_box_limit * 0.5, side_comp)
                y_c = np.linspace(-comp_box_limit * 0.5, comp_box_limit * 0.5, side_comp)
                z_c = np.linspace(-comp_box_limit * 0.5, comp_box_limit * 0.5, side_comp)
                xv_c, yv_c, zv_c = np.meshgrid(x_c, y_c, z_c)
                local_pos = np.column_stack((xv_c.flatten(), yv_c.flatten(), zv_c.flatten()))[:n_comp_nodes].astype(np.float32)

            layer_grid = c_idx_in_batch // (grid_side * grid_side)
            rem = c_idx_in_batch % (grid_side * grid_side)
            row_grid = rem // grid_side
            col_grid = rem % grid_side
            
            offset_x = (col_grid - grid_side / 2.0) * spacing
            offset_y = (row_grid - grid_side / 2.0) * spacing
            offset_z = (layer_grid - grid_side / 2.0) * spacing
            
            local_pos[:, 0] += offset_x
            local_pos[:, 1] += offset_y
            local_pos[:, 2] += offset_z

            batch_pos_list.append(local_pos)

            for (u, v), score in zip(c_edges, c_scores):
                batch_edges_list.append((global_to_batch[u], global_to_batch[v]))
                batch_scores_list.append(score)

        # Unify the arrays for the batch
        batch_pos = np.vstack(batch_pos_list).astype(np.float32)
        batch_box_limit = (np.sqrt(n_batch_nodes) * 2.5 + 5.0) * params.get('BOX_SCALE', 1.0)
        batch_comp_labels = np.zeros(n_batch_nodes, dtype=np.int32)

        batch_pos += np.random.normal(0, 0.1, batch_pos.shape).astype(np.float32)

        if is_large_job:
             print(f"\nSimulating Large Component {job_idx+1}/{len(jobs)} ({n_batch_nodes} nodes)...")
        else:
             print(f"\nSimulating Batch {job_idx+1}/{len(jobs)} ({len(batch_comps)} components, {n_batch_nodes} nodes)...")

        cutoffs = [params.get('SIMILARITY_THRESHOLD', 0.0)]
        if is_large_job and params.get('ENABLE_PROGRESSIVE_SIMULATION', True) and n_batch_nodes > 2000 and len(batch_scores_list) > 10:
            sorted_local = np.sort(batch_scores_list)[::-1] 
            n_edges = len(sorted_local)
            fractions = [0.2, 0.4, 0.6, 0.8, 1.0]
            indices = [max(0, min(int(n_edges * f) - 1, n_edges - 1)) for f in fractions]
            raw_cutoffs = [sorted_local[i] for i in indices]
            
            cutoffs = []
            for c in raw_cutoffs:
                if not cutoffs or c < cutoffs[-1]:
                    cutoffs.append(c)
                    
            if not cutoffs or cutoffs[-1] > params.get('SIMILARITY_THRESHOLD', 0.0):
                cutoffs.append(params.get('SIMILARITY_THRESHOLD', 0.0))
            else:
                cutoffs[-1] = params.get('SIMILARITY_THRESHOLD', 0.0)
                
            print(f"  > Massive component detected. Using {len(cutoffs)}-stage progressive annealing (Edge-based).")
        
        for stage, cutoff in enumerate(cutoffs):
            if len(cutoffs) > 1:
                stage_edge_count = sum(1 for s in batch_scores_list if s >= cutoff)
                print(f"  > Stage {stage+1}/{len(cutoffs)}: Cutoff = {cutoff:.3f} | Active Edges: {stage_edge_count}")

            stage_edges = [edge for edge, score in zip(batch_edges_list, batch_scores_list) if score >= cutoff]

            if len(stage_edges) > 0:
                local_edges = np.array(stage_edges, dtype=np.int32)
            else:
                local_edges = np.zeros((0, 2), dtype=np.int32)
                
            if HAS_TORCH and torch.cuda.is_available():
                sim = SSNSimulationGPU(batch_pos, local_edges, batch_comp_labels, batch_box_limit, params)
            else:
                sim = SSNSimulationCPU(batch_pos, local_edges, batch_comp_labels, batch_box_limit, params)
                
            rmsd_window = params.get('RMSD_WINDOW', 50)
            max_steps = params.get('MAX_STEPS', 2000)
            rmsd_buffer = deque(maxlen=rmsd_window)
            avg_history = []
            
            for step in range(max_steps):
                rmsd = sim.step(step, apply_warmup=(stage == 0))
                rmsd_buffer.append(rmsd)
                avg_rmsd = np.mean(rmsd_buffer)
                
                if step > 0 and step % 500 == 0:
                    print(f"    - Step {step:04d}/{max_steps}: RMSD = {avg_rmsd:.5f}")
                    
                if len(rmsd_buffer) == rmsd_window:
                    avg_history.append(avg_rmsd)
                    
                    if avg_rmsd < params.get('RMSD_THRESHOLD', 0.005):
                        print(f"    - Converged at Step {step} (RMSD: {avg_rmsd:.5f})")
                        break
                        
                    pct_threshold = params.get('PERCENTAGE_DROP_THRESHOLD', 0.0)
                    warmup_steps = max_steps / 4.0
                    trend_window = 10
                    
                    if pct_threshold > 0.0 and len(avg_history) >= (rmsd_window + trend_window) and step > warmup_steps:
                        current_trend = np.mean(avg_history[-trend_window:])
                        old_trend = np.mean(avg_history[-(rmsd_window + trend_window):-rmsd_window])
                        
                        if old_trend > 0:
                            pct_drop = ((old_trend - current_trend) / old_trend) * 100.0
                            if pct_drop < pct_threshold:
                                print(f"    - Plateau Reached at Step {step} (Drop: {pct_drop:.3f}% < {pct_threshold}%)")
                                break
                    
            batch_pos = sim.get_pos()
            
            del sim
            if HAS_TORCH and torch.cuda.is_available():
                torch.cuda.empty_cache()
                
        # Update the final positions
        final_pos[batch_global_nodes] = batch_pos
            
    print("\nSimulation Complete.")
    
    # Pack independent components into a grid
    final_pos, final_box_limit = pack_components_to_grid(
        final_pos, edges, n_nodes, 
        params.get('PACKING_GRID_SIZE', 200.0), 
        params.get('PACKING_PADDING', 50.0)
    )
    
    return final_pos, final_box_limit

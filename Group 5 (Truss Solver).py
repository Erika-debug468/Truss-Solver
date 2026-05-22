import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import math

# Peg zero to positive to completely prevent -0.0 displaying
def format_val(val, decimals):
    rounded = round(float(val), decimals)
    if rounded == 0.0:
        return f"{0.0:.{decimals}f}"
    return f"{rounded:.{decimals}f}"


class LoadDialog(tk.Toplevel):
    def __init__(self, parent, title="Add Load"):
        super().__init__(parent)
        self.title(title)
        self.result = None

        #GUI
        ttk.Label(self, text="Fx (kN): [Right is +]", foreground="red").grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        self.fx_entry = ttk.Entry(self)
        self.fx_entry.insert(0, "0.0")
        self.fx_entry.grid(row=0, column=1, padx=10, pady=(10, 5))

        ttk.Label(self, text="Fy (kN): [Up is +]", foreground="red").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.fy_entry = ttk.Entry(self)
        self.fy_entry.insert(0, "0.0")
        self.fy_entry.grid(row=1, column=1, padx=10, pady=5)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=10)

        ttk.Button(btn_frame, text="Apply Load", command=self.on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.bind('<Return>', lambda e: self.on_ok())
        self.fx_entry.focus_set()

        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    def on_ok(self):
        try:
            fx = float(self.fx_entry.get())
            fy = float(self.fy_entry.get())
            self.result = (fx, fy)
            self.destroy()
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numeric values.")


class TrussApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Truss Solver")
        self.root.geometry("1400x850")

        # 50 pixels on screen = 1 meter in real life
        self.scale = 50.0

        # Data structures with Unique IDs for robust deletion
        self.nodes = {}       # node_id: (x, y)
        self.members = {}     # member_id: (node1_id, node2_id, A_mm2, E_GPa)
        self.loads = {}       # load_id: (node_id, fx_kN, fy_kN)
        self.supports = {}    # node_id: (type, angle)

        self.node_counter = 0
        self.member_counter = 0
        self.load_counter = 0

        self.mode_var = tk.StringVar(value="node")
        self.selected_node = None

        # Deflections are calculated after the method-of-joints solve using unit-load virtual work.
        self.show_deflected_var = tk.BooleanVar(value=False)
        self.deflection_mag_var = tk.StringVar(value="1000")
        self.U_dict = {}
        self.member_colors = {}

        self.create_ui()

        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Motion>", self.show_cursor_coordinates)

        self.redraw()

    def create_ui(self):
        toolbar = ttk.Frame(self.root, padding=5, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        mode_frame = ttk.LabelFrame(toolbar, text="Inputs", padding=5)
        mode_frame.pack(side=tk.LEFT, padx=10)

        modes = [("Add Node", "node"), ("Add Member", "member"),
                 ("Add Load", "load"), ("Add Support", "support")]

        for text, mode in modes:
            ttk.Radiobutton(mode_frame, text=text, variable=self.mode_var, value=mode,
                            style="Toolbutton", command=self.reset_selection).pack(side=tk.LEFT, padx=2)

        prop_frame = ttk.LabelFrame(toolbar, text="Parameters (Members & Supports)", padding=5)
        prop_frame.pack(side=tk.LEFT, padx=10)

        ttk.Label(prop_frame, text="E (GPa):").pack(side=tk.LEFT)
        self.E_var = tk.StringVar(value="200")
        ttk.Entry(prop_frame, textvariable=self.E_var, width=6).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(prop_frame, text="A (mm2):").pack(side=tk.LEFT)
        self.A_var = tk.StringVar(value="2000")
        ttk.Entry(prop_frame, textvariable=self.A_var, width=8).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(prop_frame, text="Support:").pack(side=tk.LEFT)
        self.support_var = tk.StringVar(value="pin")
        ttk.Combobox(prop_frame, textvariable=self.support_var, values=["pin", "roller"],
                     state="readonly", width=8).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Label(prop_frame, text="Angle (deg):").pack(side=tk.LEFT)
        self.roller_angle_var = tk.StringVar(value="0")
        ttk.Entry(prop_frame, textvariable=self.roller_angle_var, width=4).pack(side=tk.LEFT)

        action_frame = ttk.Frame(toolbar, padding=5)
        action_frame.pack(side=tk.RIGHT, padx=10)

        self.coord_label = ttk.Label(action_frame, text="X: 0 m, Y: 0 m", font=("Arial", 10, "bold"), foreground="blue")
        self.coord_label.pack(side=tk.LEFT, padx=20)

        ttk.Checkbutton(action_frame, text="Show Deflected", variable=self.show_deflected_var, command=lambda: self.redraw(self.member_colors)).pack(side=tk.LEFT, padx=5)
        ttk.Label(action_frame, text="Mag:").pack(side=tk.LEFT)
        ttk.Entry(action_frame, textvariable=self.deflection_mag_var, width=5).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(action_frame, text="Clear All", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_frame, text="SOLVE TRUSS", command=self.solve, style="Accent.TButton").pack(side=tk.LEFT)

        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        canvas_frame = ttk.Frame(paned)
        paned.add(canvas_frame, weight=3)
        self.canvas = tk.Canvas(canvas_frame, bg="white", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(paned)
        paned.add(self.notebook, weight=1)

        self.create_input_tab()
        self.create_results_tab()

    def create_input_tab(self):
        input_tab = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(input_tab, text="Inputs & Editing")

        v_paned = ttk.PanedWindow(input_tab, orient=tk.VERTICAL)
        v_paned.pack(fill=tk.BOTH, expand=True)

        def create_list_section(parent, title, columns):
            frame = ttk.LabelFrame(parent, text=title)
            tree_frame = ttk.Frame(frame)
            tree_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=3)
            for col in columns:
                tree.heading(col, text=col)
                tree.column(col, width=50, anchor=tk.CENTER)

            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            return frame, tree

        f_nodes, self.tree_nodes = create_list_section(v_paned, "Nodes", ("ID", "X (m)", "Y (m)"))
        ttk.Button(f_nodes, text="Delete Selected Node", command=self.delete_node).pack(anchor=tk.E, padx=5, pady=2)
        v_paned.add(f_nodes, weight=1)

        f_members, self.tree_members = create_list_section(v_paned, "Members", ("ID", "N1", "N2", "A", "E"))
        ttk.Button(f_members, text="Delete Selected Member", command=self.delete_member).pack(anchor=tk.E, padx=5, pady=2)
        v_paned.add(f_members, weight=1)

        f_loads, self.tree_loads = create_list_section(v_paned, "Loads", ("ID", "Node", "Fx (kN)", "Fy (kN)"))
        ttk.Button(f_loads, text="Delete Selected Load", command=self.delete_load).pack(anchor=tk.E, padx=5, pady=2)
        v_paned.add(f_loads, weight=1)

        f_supports, self.tree_supports = create_list_section(v_paned, "Supports", ("Node", "Type", "Angle"))
        ttk.Button(f_supports, text="Delete Selected Support", command=self.delete_support).pack(anchor=tk.E, padx=5, pady=2)
        v_paned.add(f_supports, weight=1)

    def create_results_tab(self):
        result_tab = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(result_tab, text="Results Summary")

        v_paned = ttk.PanedWindow(result_tab, orient=tk.VERTICAL)
        v_paned.pack(fill=tk.BOTH, expand=True)

        mf_frame = ttk.LabelFrame(v_paned, text="Member Forces")
        self.tree_res_members = ttk.Treeview(mf_frame, columns=("Member", "Force (kN)", "State"), show="headings", height=5)
        self.tree_res_members.heading("Member", text="Member")
        self.tree_res_members.heading("Force (kN)", text="Force (kN)")
        self.tree_res_members.heading("State", text="State")
        self.tree_res_members.column("Member", width=80, anchor=tk.CENTER)
        self.tree_res_members.column("Force (kN)", width=100, anchor=tk.CENTER)
        self.tree_res_members.column("State", width=120, anchor=tk.CENTER)
        self.tree_res_members.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        v_paned.add(mf_frame, weight=2)

        df_frame = ttk.LabelFrame(v_paned, text="Nodal Deflections")
        self.tree_res_disp = ttk.Treeview(df_frame, columns=("Node", "Ux (mm)", "Uy (mm)"), show="headings", height=4)
        for col in ("Node", "Ux (mm)", "Uy (mm)"):
            self.tree_res_disp.heading(col, text=col)
            self.tree_res_disp.column(col, width=80, anchor=tk.CENTER)
        self.tree_res_disp.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        v_paned.add(df_frame, weight=1)

        rx_frame = ttk.LabelFrame(v_paned, text="Support Reactions")
        self.tree_res_react = ttk.Treeview(rx_frame, columns=("Node", "Rx (kN)", "Ry (kN)"), show="headings", height=3)
        for col in ("Node", "Rx (kN)", "Ry (kN)"):
            self.tree_res_react.heading(col, text=col)
            self.tree_res_react.column(col, width=80, anchor=tk.CENTER)
        self.tree_res_react.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        v_paned.add(rx_frame, weight=1)

    def reset_selection(self):
        self.selected_node = None
        self.redraw()

    def show_cursor_coordinates(self, event):
        x_m = round(event.x / self.scale)
        y_m = round(event.y / self.scale)
        self.coord_label.config(text=f"X: {x_m} m, Y: {y_m} m")

    def click(self, event):
        x_m = round(event.x / self.scale)
        y_m = round(event.y / self.scale)
        mode = self.mode_var.get()

        clicked_node_id = None
        for n_id, (nx, ny) in self.nodes.items():
            if abs(nx - x_m) < 0.2 and abs(ny - y_m) < 0.2:
                clicked_node_id = n_id
                break

        if mode == "node":
            if clicked_node_id is None:
                self.nodes[self.node_counter] = (x_m, y_m)
                self.node_counter += 1

        elif mode == "member":
            if clicked_node_id is not None:
                if self.selected_node is None:
                    self.selected_node = clicked_node_id
                else:
                    if self.selected_node != clicked_node_id:
                        exists = any((m[0] == self.selected_node and m[1] == clicked_node_id) or
                                     (m[1] == self.selected_node and m[0] == clicked_node_id)
                                     for m in self.members.values())
                        if not exists:
                            try:
                                E = float(self.E_var.get())
                                A = float(self.A_var.get())
                                self.members[self.member_counter] = (self.selected_node, clicked_node_id, A, E)
                                self.member_counter += 1
                            except ValueError:
                                messagebox.showerror("Error", "Invalid Material Properties.")
                    self.selected_node = None

        elif mode == "load":
            if clicked_node_id is not None:
                d = LoadDialog(self.root, title=f"Load at Node {clicked_node_id}")
                if d.result:
                    fx, fy = d.result
                    if fx != 0 or fy != 0:
                        self.loads[self.load_counter] = (clicked_node_id, fx, fy)
                        self.load_counter += 1

        elif mode == "support":
            if clicked_node_id is not None:
                try:
                    angle = float(self.roller_angle_var.get())
                    self.supports[clicked_node_id] = (self.support_var.get(), angle)
                except ValueError:
                    messagebox.showerror("Error", "Invalid Support Angle.")

        self.update_input_tables()
        self.redraw(self.member_colors)

    def get_selected_id(self, tree):
        selected = tree.selection()
        if not selected:
            return None
        return int(tree.item(selected[0])['values'][0])

    def delete_node(self):
        n_id = self.get_selected_id(self.tree_nodes)
        if n_id is not None:
            to_delete = [m_id for m_id, m in self.members.items() if m[0] == n_id or m[1] == n_id]
            for m_id in to_delete:
                del self.members[m_id]
            l_to_delete = [l_id for l_id, l in self.loads.items() if l[0] == n_id]
            for l_id in l_to_delete:
                del self.loads[l_id]
            self.supports.pop(n_id, None)
            del self.nodes[n_id]
            self.update_input_tables()
            self.redraw(self.member_colors)

    def delete_member(self):
        m_id = self.get_selected_id(self.tree_members)
        if m_id is not None:
            del self.members[m_id]
            self.update_input_tables()
            self.redraw(self.member_colors)

    def delete_load(self):
        l_id = self.get_selected_id(self.tree_loads)
        if l_id is not None:
            del self.loads[l_id]
            self.update_input_tables()
            self.redraw(self.member_colors)

    def delete_support(self):
        selected = self.tree_supports.selection()
        if selected:
            n_id = int(self.tree_supports.item(selected[0])['values'][0])
            del self.supports[n_id]
            self.update_input_tables()
            self.redraw(self.member_colors)

    def clear_all(self):
        self.nodes.clear()
        self.members.clear()
        self.loads.clear()
        self.supports.clear()
        self.U_dict.clear()
        self.member_colors.clear()
        self.node_counter = 0
        self.member_counter = 0
        self.load_counter = 0
        self.selected_node = None
        self.update_input_tables()
        for tree in (self.tree_res_members, self.tree_res_disp, self.tree_res_react):
            for item in tree.get_children():
                tree.delete(item)
        self.redraw()

    def update_input_tables(self):
        for tree in (self.tree_nodes, self.tree_members, self.tree_loads, self.tree_supports):
            for item in tree.get_children():
                tree.delete(item)

        for n_id, (x, y) in self.nodes.items():
            self.tree_nodes.insert("", tk.END, values=(n_id, format_val(x, 1), format_val(y, 1)))
        for m_id, (n1, n2, A, E) in self.members.items():
            self.tree_members.insert("", tk.END, values=(m_id, n1, n2, A, E))
        for l_id, (n_id, fx, fy) in self.loads.items():
            self.tree_loads.insert("", tk.END, values=(l_id, n_id, format_val(fx, 2), format_val(fy, 2)))
        for n_id, (stype, angle) in self.supports.items():
            self.tree_supports.insert("", tk.END, values=(n_id, stype, format_val(angle, 1)))

    def get_nodal_forces(self):
        f_dict = {n_id: [0.0, 0.0] for n_id in self.nodes}
        for (n_id, fx, fy) in self.loads.values():
            if n_id in f_dict:
                f_dict[n_id][0] += fx
                f_dict[n_id][1] += fy
        return f_dict

    def get_member_length(self, n1, n2):
        x1, y1_screen = self.nodes[n1]
        x2, y2_screen = self.nodes[n2]
        dx = x2 - x1
        dy = -(y2_screen - y1_screen)
        length = math.hypot(dx, dy)
        if length == 0:
            raise ValueError(f"Member between Node {n1} and Node {n2} has zero length.")
        return length

    def get_member_direction(self, from_node, to_node):
        # Screen Y is down, but force equilibrium uses positive Y upward.
        x1, y1_screen = self.nodes[from_node]
        x2, y2_screen = self.nodes[to_node]
        dx = x2 - x1
        dy = -(y2_screen - y1_screen)
        length = self.get_member_length(from_node, to_node)
        return dx / length, dy / length

    def get_reaction_unknowns(self):
        reactions = []
        for n_id, (stype, angle) in self.supports.items():
            if stype == "pin":
                reactions.append((n_id, "Rx", 1.0, 0.0))
                reactions.append((n_id, "Ry", 0.0, 1.0))
            elif stype == "roller":
                rad = math.radians(angle)
                nx = -math.sin(rad)
                ny = math.cos(rad)
                reactions.append((n_id, "R", nx, ny))
        return reactions

    def solve_joint_equilibrium(self, nodal_forces):
        node_list = list(self.nodes.keys())
        node_row = {n_id: i for i, n_id in enumerate(node_list)}
        member_ids = list(self.members.keys())
        reaction_unknowns = self.get_reaction_unknowns()

        unknown_count = len(member_ids) + len(reaction_unknowns)
        equation_count = 2 * len(node_list)

        if unknown_count != equation_count:
            raise ValueError(
                "Method of joints requires a statically determinate truss.\n"
                f"Equations: {equation_count}, Unknowns: {unknown_count} "
                f"({len(member_ids)} members + {len(reaction_unknowns)} reactions)."
            )

        A = np.zeros((equation_count, unknown_count))
        b = np.zeros(equation_count)

        for n_id in node_list:
            row_x = 2 * node_row[n_id]
            row_y = row_x + 1
            load_fx, load_fy = nodal_forces.get(n_id, (0.0, 0.0))
            b[row_x] = -load_fx
            b[row_y] = -load_fy

        for col, m_id in enumerate(member_ids):
            n1, n2, _A_mm2, _E_GPa = self.members[m_id]
            c12, s12 = self.get_member_direction(n1, n2)
            r1 = 2 * node_row[n1]
            r2 = 2 * node_row[n2]

            # Positive member force is tension, pulling away from each joint.
            A[r1, col] += c12
            A[r1 + 1, col] += s12
            A[r2, col] -= c12
            A[r2 + 1, col] -= s12

        offset = len(member_ids)
        for i, (n_id, _label, rx_dir, ry_dir) in enumerate(reaction_unknowns):
            row = 2 * node_row[n_id]
            A[row, offset + i] += rx_dir
            A[row + 1, offset + i] += ry_dir

        try:
            solution = np.linalg.solve(A, b)
        except np.linalg.LinAlgError as exc:
            raise ValueError("Joint equilibrium equations are singular. Check stability, supports, and member layout.") from exc

        residual = A @ solution - b
        if np.linalg.norm(residual, ord=np.inf) > 1e-6:
            raise ValueError("Joint equilibrium could not be satisfied. Check the model geometry and loads.")

        member_forces = {m_id: solution[i] for i, m_id in enumerate(member_ids)}
        reactions = {n_id: [0.0, 0.0] for n_id in self.supports}

        for i, (n_id, _label, rx_dir, ry_dir) in enumerate(reaction_unknowns):
            value = solution[offset + i]
            reactions[n_id][0] += value * rx_dir
            reactions[n_id][1] += value * ry_dir

        return member_forces, reactions

    def calculate_virtual_work_deflections(self, real_member_forces):
        displacements = {}
        unit_load_kN = 0.001  # 1 N, while the app's force input/output remains in kN.

        for target_node in self.nodes:
            displacements[target_node] = []
            for dof in ("x", "y"):
                virtual_loads = {n_id: [0.0, 0.0] for n_id in self.nodes}
                if dof == "x":
                    virtual_loads[target_node][0] = unit_load_kN
                else:
                    virtual_loads[target_node][1] = unit_load_kN

                virtual_member_forces, _virtual_reactions = self.solve_joint_equilibrium(virtual_loads)
                displacement_m = 0.0

                for m_id, real_force_kN in real_member_forces.items():
                    n1, n2, A_mm2, E_GPa = self.members[m_id]
                    length = self.get_member_length(n1, n2)
                    area = A_mm2 * 1e-6
                    elastic_modulus = E_GPa * 1e9
                    real_force_N = real_force_kN * 1000.0
                    virtual_force_N = virtual_member_forces[m_id] * 1000.0
                    displacement_m += (real_force_N * virtual_force_N * length) / (area * elastic_modulus)

                displacements[target_node].append(displacement_m)

        return {n_id: (values[0], values[1]) for n_id, values in displacements.items()}

    def solve(self):
        if not self.nodes or not self.members:
            messagebox.showwarning("Warning", "Structure is incomplete.")
            return

        try:
            nodal_forces = self.get_nodal_forces()
            member_forces, reactions = self.solve_joint_equilibrium(nodal_forces)
            self.U_dict = self.calculate_virtual_work_deflections(member_forces)
            self.show_results(member_forces, reactions, self.U_dict)
            self.notebook.select(1)

        except Exception as e:
            messagebox.showerror("Solver Error", str(e))

    def show_results(self, member_forces, reactions, displacements):
        for tree in (self.tree_res_members, self.tree_res_disp, self.tree_res_react):
            for item in tree.get_children():
                tree.delete(item)

        member_colors = {}

        for m_id, force_kN in member_forces.items():
            n1, n2, _A_mm2, _E_GPa = self.members[m_id]
            if abs(force_kN) < 0.001:
                state, col = "ZERO", "gray"
            elif force_kN > 0:
                state, col = "TENSION", "blue"
            else:
                state, col = "COMPRESSION", "red"

            member_colors[m_id] = col
            self.tree_res_members.insert("", tk.END, values=(f"ID {m_id} ({n1}-{n2})", format_val(abs(force_kN), 3), state))

        for n_id in self.nodes:
            ux_mm = displacements[n_id][0] * 1000.0
            uy_mm = displacements[n_id][1] * 1000.0
            self.tree_res_disp.insert("", tk.END, values=(n_id, format_val(ux_mm, 4), format_val(uy_mm, 4)))

        for n_id, (rx_kN, ry_kN) in reactions.items():
            self.tree_res_react.insert("", tk.END, values=(n_id, format_val(rx_kN, 3), format_val(ry_kN, 3)))

        self.member_colors = member_colors
        self.redraw(self.member_colors)

    def draw_grid(self):
        w = self.canvas.winfo_width() or 2000
        h = self.canvas.winfo_height() or 2000
        spacing = int(self.scale)

        for x in range(0, w, spacing):
            self.canvas.create_line(x, 0, x, h, fill="#f0f0f0")
            if x % (spacing * 2) == 0:
                self.canvas.create_text(x + 2, 2, text=str(x // spacing), fill="#aaa", anchor="nw", font=("Arial", 7))

        for y in range(0, h, spacing):
            self.canvas.create_line(0, y, w, y, fill="#f0f0f0")
            if y % (spacing * 2) == 0:
                self.canvas.create_text(2, y + 2, text=str(y // spacing), fill="#aaa", anchor="nw", font=("Arial", 7))

    def draw_support(self, cx, cy, stype, angle=0):
        if stype == "pin":
            self.canvas.create_polygon(cx, cy + 8, cx - 10, cy + 20, cx + 10, cy + 20, fill="green", outline="black")
        elif stype == "roller":
            rad = -math.radians(angle)
            s = math.sin(rad)
            c = math.cos(rad)

            def rot(px, py):
                return cx + (px * c - py * s), cy + (px * s + py * c)

            p1 = rot(0, 8)
            p2 = rot(-10, 18)
            p3 = rot(10, 18)
            self.canvas.create_polygon(*p1, *p2, *p3, fill="green", outline="black")

            c1 = rot(-5, 21)
            c2 = rot(5, 21)
            r = 3
            self.canvas.create_oval(c1[0] - r, c1[1] - r, c1[0] + r, c1[1] + r, fill="black")
            self.canvas.create_oval(c2[0] - r, c2[1] - r, c2[0] + r, c2[1] + r, fill="black")

            l1 = rot(-15, 24)
            l2 = rot(15, 24)
            self.canvas.create_line(*l1, *l2, width=2, fill="black")

    def redraw(self, member_colors=None):
        self.canvas.delete("all")
        self.draw_grid()

        is_deflected = self.show_deflected_var.get()

        for m_id, (n1, n2, _A, _E) in self.members.items():
            x1, y1 = self.nodes[n1]
            x2, y2 = self.nodes[n2]
            cx1, cy1 = x1 * self.scale, y1 * self.scale
            cx2, cy2 = x2 * self.scale, y2 * self.scale

            color = member_colors.get(m_id, "black") if member_colors else "black"

            if is_deflected and self.U_dict:
                self.canvas.create_line(cx1, cy1, cx2, cy2, width=1, fill="#cccccc")
            else:
                self.canvas.create_line(cx1, cy1, cx2, cy2, width=3, fill=color)

        if is_deflected and self.U_dict:
            try:
                mag = float(self.deflection_mag_var.get())
            except ValueError:
                mag = 100.0

            for m_id, (n1, n2, _A, _E) in self.members.items():
                ux1, uy1 = self.U_dict.get(n1, (0, 0))
                ux2, uy2 = self.U_dict.get(n2, (0, 0))

                cx1 = (self.nodes[n1][0] + ux1 * mag) * self.scale
                cy1 = (self.nodes[n1][1] - uy1 * mag) * self.scale
                cx2 = (self.nodes[n2][0] + ux2 * mag) * self.scale
                cy2 = (self.nodes[n2][1] - uy2 * mag) * self.scale

                color = member_colors.get(m_id, "magenta") if member_colors else "magenta"
                self.canvas.create_line(cx1, cy1, cx2, cy2, width=3, fill=color, dash=(4, 2))

        for n_id, (x, y) in self.nodes.items():
            cx, cy = x * self.scale, y * self.scale

            if n_id == self.selected_node:
                self.canvas.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill="red")
            else:
                self.canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill="blue")

            self.canvas.create_text(cx + 8, cy - 8, text=f"N{n_id}", font=("Arial", 9, "bold"), fill="blue", anchor="sw")

            if n_id in self.supports:
                stype, angle = self.supports[n_id]
                self.draw_support(cx, cy, stype, angle)

        nodal_forces = self.get_nodal_forces()
        for n_id, (fx_kN, fy_kN) in nodal_forces.items():
            if fx_kN == 0 and fy_kN == 0:
                continue

            cx, cy = self.nodes[n_id][0] * self.scale, self.nodes[n_id][1] * self.scale

            arrow_x = cx + (fx_kN * 2)
            arrow_y = cy - (fy_kN * 2)

            self.canvas.create_line(cx, cy, arrow_x, arrow_y, arrow=tk.LAST, fill="red", width=2)
            self.canvas.create_text(arrow_x + 5, arrow_y - 5, text=f"{format_val(fx_kN, 1)}kN, {format_val(fy_kN, 1)}kN",
                                    fill="red", font=("Arial", 8, "bold"), anchor="sw")


if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    style.theme_use('clam')
    app = TrussApp(root)
    root.mainloop()





 
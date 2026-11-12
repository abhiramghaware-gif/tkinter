"""Phase 6 Emergency Inventory & Atomic Resource Allocation GUI tabs."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from config import (
    ALLOCATION_RESOURCE_TYPES,
    INVENTORY_CATEGORIES,
    INVENTORY_SUBTYPE_EXAMPLES,
    INVENTORY_VERIFICATION_STATUSES,
    THEME,
)
from core.models import Neighbourhood
from core.validation import ValidationError
from emergency.inventory_manager import InventoryItemRecord, InventoryManager
from emergency.inventory_transactions import InventoryTransactionRecord, InventoryTransactionService
from emergency.operation_manager import EmergencyOperationRecord, OperationManager
from emergency.rescue_team_manager import RescueTeamManager, RescueTeamRecord
from emergency.resource_allocator import ResourceAllocationRecord, ResourceAllocator
from emergency.shelter_manager import ShelterManager, ShelterRecord
from emergency.vehicle_manager import VehicleManager, VehicleRecord
from emergency.volunteer_manager import VolunteerManager, VolunteerRecord


class InventoryTab(tk.Frame):
    """Inventory registry, verified vs unverified badges, stock movements & audit transactions."""

    def __init__(
        self,
        parent: tk.Misc,
        inv_mgr: InventoryManager,
        tx_svc: InventoryTransactionService,
        on_data_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.inv_mgr = inv_mgr
        self.tx_svc = tx_svc
        self.on_data_changed = on_data_changed

        self._neighbourhood: Neighbourhood | None = None
        self._items: list[InventoryItemRecord] = []
        self._txs: list[InventoryTransactionRecord] = []
        self._selected_id: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        banner = tk.Frame(
            self,
            bg=THEME["warning_bg"],
            highlightbackground=THEME["warning"],
            highlightthickness=1,
            padx=10,
            pady=5,
        )
        banner.pack(fill="x", pady=(0, 8))
        tk.Label(
            banner,
            text=(
                "INVENTORY VERIFICATION POLICY: All newly registered items default to 'Registered (Unverified)' until marked "
                "'Physically Verified'. Stock levels never drop below zero and every change records an atomic transaction."
            ),
            bg=THEME["warning_bg"],
            fg="#FDE68A",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            justify="left",
            wraplength=980,
        ).pack(anchor="w", fill="x")

        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Left fixed-width scrollable panel
        outer = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=352,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=330)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        form = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=form, anchor="nw", width=330)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tk.Label(
            form,
            text="1. INVENTORY ITEM REGISTRATION",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 4))

        self.var_cat = tk.StringVar(value=INVENTORY_CATEGORIES[0])
        self.var_name = tk.StringVar()
        self.var_qty = tk.StringVar(value="0")
        self.var_unit = tk.StringVar(value="litres")
        self.var_min = tk.StringVar(value="10")
        self.var_loc = tk.StringVar(value="Primary Relief Store")
        self.var_exp = tk.StringVar()
        self.var_sup = tk.StringVar()
        self.var_ver = tk.StringVar(value=INVENTORY_VERIFICATION_STATUSES[0])
        self.var_notes = tk.StringVar()

        tk.Label(form, text="Category *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        cat_cb = ttk.Combobox(form, textvariable=self.var_cat, values=INVENTORY_CATEGORIES, state="readonly")
        cat_cb.pack(fill="x", pady=(0, 3))
        cat_cb.bind("<<ComboboxSelected>>", self._on_cat_changed)

        tk.Label(form, text="Item Name (type or pick example) *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.name_cb = ttk.Combobox(
            form, textvariable=self.var_name, values=INVENTORY_SUBTYPE_EXAMPLES[INVENTORY_CATEGORIES[0]]
        )
        self.name_cb.pack(fill="x", pady=(0, 3))

        row_qum = tk.Frame(form, bg=THEME["bg_card"])
        row_qum.pack(fill="x", pady=(2, 3))
        for col_i in range(3):
            row_qum.columnconfigure(col_i, weight=1)
        tk.Label(row_qum, text="Init Qty:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(row_qum, text="Unit *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=1, sticky="w", padx=4
        )
        tk.Label(row_qum, text="Min Stock:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=2, sticky="w"
        )
        ttk.Entry(row_qum, textvariable=self.var_qty).grid(row=1, column=0, sticky="ew")
        ttk.Entry(row_qum, textvariable=self.var_unit).grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Entry(row_qum, textvariable=self.var_min).grid(row=1, column=2, sticky="ew")

        def field(lbl: str, var: tk.StringVar) -> None:
            tk.Label(form, text=lbl, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
                anchor="w", fill="x", pady=(2, 1)
            )
            ttk.Entry(form, textvariable=var).pack(fill="x", pady=(0, 3))

        field("Storage Location:", self.var_loc)
        field("Expiry Date (YYYY-MM-DD, optional):", self.var_exp)
        field("Supplier / Source:", self.var_sup)

        tk.Label(form, text="Verification Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        ttk.Combobox(form, textvariable=self.var_ver, values=INVENTORY_VERIFICATION_STATUSES, state="readonly").pack(
            fill="x", pady=(0, 3)
        )
        field("Notes:", self.var_notes)

        btns1 = tk.Frame(form, bg=THEME["bg_card"])
        btns1.pack(fill="x", pady=(4, 6))
        btns1.columnconfigure(0, weight=1)
        btns1.columnconfigure(1, weight=1)
        ttk.Button(btns1, text="Register Item", style="Accent.TButton", command=self._register).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns1, text="Save Metadata", command=self._update_meta).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns1, text="Clear Form", command=self._clear_form).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns1, text="Delete Item", command=self._delete).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # Stock Movement Box
        tk.Label(
            form,
            text="2. STOCK MOVEMENT (Selected Item)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(6, 4))

        self.var_mv_qty = tk.StringVar(value="10")
        self.var_mv_loc = tk.StringVar()
        self.var_mv_op = tk.StringVar(value="Operator")
        self.var_mv_reason = tk.StringVar(value="Manual update")

        row_mv = tk.Frame(form, bg=THEME["bg_card"])
        row_mv.pack(fill="x", pady=(0, 3))
        row_mv.columnconfigure(0, weight=1)
        row_mv.columnconfigure(1, weight=1)
        tk.Label(row_mv, text="Movement Qty / Target:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(row_mv, text="Operator:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        ttk.Entry(row_mv, textvariable=self.var_mv_qty).grid(row=1, column=0, sticky="ew", padx=(0, 3))
        ttk.Entry(row_mv, textvariable=self.var_mv_op).grid(row=1, column=1, sticky="ew", padx=(3, 0))

        field("Target / Source Location (for Transfer):", self.var_mv_loc)
        field("Reason / Audit Note:", self.var_mv_reason)

        btns2 = tk.Frame(form, bg=THEME["bg_card"])
        btns2.pack(fill="x", pady=(3, 2))
        btns2.columnconfigure(0, weight=1)
        btns2.columnconfigure(1, weight=1)
        ttk.Button(btns2, text="Add Stock (+)", style="Accent.TButton", command=self._add_stock).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns2, text="Deduct Stock (-)", command=self._deduct_stock).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns2, text="Adjust Stock (=)", command=self._adjust_stock).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns2, text="Transfer Location", command=self._transfer_stock).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # Right side split: Top Inventory list, Bottom Stock Transaction Log
        right = tk.Frame(body, bg=THEME["bg_root"])
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)
        right.columnconfigure(0, weight=1)

        inv_card = tk.Frame(
            right,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        inv_card.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        inv_card.rowconfigure(1, weight=1)
        inv_card.columnconfigure(0, weight=1)

        filt = tk.Frame(inv_card, bg=THEME["bg_card"])
        filt.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(filt, text="Search:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_search = tk.StringVar()
        e_s = ttk.Entry(filt, textvariable=self.var_search, width=18)
        e_s.pack(side="left", padx=(4, 8))
        e_s.bind("<KeyRelease>", lambda _e: self.refresh())

        tk.Label(filt, text="Category:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_cat_filter = tk.StringVar(value="All")
        cb_c = ttk.Combobox(filt, textvariable=self.var_cat_filter, values=("All",) + INVENTORY_CATEGORIES, state="readonly", width=16)
        cb_c.pack(side="left", padx=(4, 8))
        cb_c.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.var_low_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(filt, text="Low Stock Only", variable=self.var_low_only, command=self.refresh).pack(side="left", padx=(2, 6))

        self.summary_lbl = tk.Label(filt, text="0 item(s)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.summary_lbl.pack(side="right")

        cols = ("id", "name", "cat", "qty", "unit", "min", "flags", "exp", "ver", "loc")
        wrap_i = tk.Frame(inv_card, bg=THEME["bg_card"])
        wrap_i.grid(row=1, column=0, sticky="nsew")
        wrap_i.rowconfigure(0, weight=1)
        wrap_i.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap_i, columns=cols, show="headings", selectmode="browse")
        for k, h, w in [
            ("id", "ID", 36),
            ("name", "Item Name", 150),
            ("cat", "Category", 115),
            ("qty", "Qty", 62),
            ("unit", "Unit", 62),
            ("min", "Min", 55),
            ("flags", "Stock Status", 105),
            ("exp", "Expiry", 96),
            ("ver", "Verification", 125),
            ("loc", "Storage Location", 130),
        ]:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="e" if k in ("id", "qty", "min") else "w")
        self.tree.tag_configure("low", foreground="#FCD34D")
        self.tree.tag_configure("zero", foreground="#FCA5A5")
        vsb_i = ttk.Scrollbar(wrap_i, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_i.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb_i.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Bottom transaction history table
        tx_card = tk.Frame(
            right,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        tx_card.grid(row=1, column=0, sticky="nsew")
        tx_card.rowconfigure(1, weight=1)
        tx_card.columnconfigure(0, weight=1)

        tk.Label(
            tx_card,
            text="STOCK TRANSACTION AUDIT HISTORY (SQLite Atomic Log)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))

        tcols = ("id", "type", "item", "qty", "from_to", "op", "reason", "ts")
        wrap_tx = tk.Frame(tx_card, bg=THEME["bg_card"])
        wrap_tx.grid(row=1, column=0, sticky="nsew")
        wrap_tx.rowconfigure(0, weight=1)
        wrap_tx.columnconfigure(0, weight=1)
        self.tx_tree = ttk.Treeview(wrap_tx, columns=tcols, show="headings", height=6)
        for k, h, w in [
            ("id", "Tx#", 40),
            ("type", "Transaction", 115),
            ("item", "Item", 135),
            ("qty", "Qty", 75),
            ("from_to", "From -> To", 170),
            ("op", "Operator", 90),
            ("reason", "Reason", 160),
            ("ts", "Timestamp UTC", 135),
        ]:
            self.tx_tree.heading(k, text=h)
            self.tx_tree.column(k, width=w, anchor="e" if k in ("id", "qty") else "w")
        vsb_tx = ttk.Scrollbar(wrap_tx, orient="vertical", command=self.tx_tree.yview)
        self.tx_tree.configure(yscrollcommand=vsb_tx.set)
        self.tx_tree.grid(row=0, column=0, sticky="nsew")
        vsb_tx.grid(row=0, column=1, sticky="ns")

    def _on_cat_changed(self, _evt=None) -> None:
        cat = self.var_cat.get()
        self.name_cb.configure(values=INVENTORY_SUBTYPE_EXAMPLES.get(cat, ()))

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        if (neighbourhood.id if neighbourhood else None) != (self._neighbourhood.id if self._neighbourhood else None):
            self._selected_id = None
            self._clear_form()
        self._neighbourhood = neighbourhood
        self.refresh()

    def refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for tid in self.tx_tree.get_children():
            self.tx_tree.delete(tid)
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._items = []
            self._txs = []
            self.summary_lbl.configure(text="No active workspace")
            return

        self._items = self.inv_mgr.list_items(
            self._neighbourhood.id,
            category_filter=self.var_cat_filter.get(),
            low_stock_only=bool(self.var_low_only.get()),
            search=self.var_search.get(),
        )
        low_cnt = sum(1 for i in self._items if i.is_low_stock)
        self.summary_lbl.configure(text=f"{len(self._items)} item(s) • {low_cnt} low/out of stock")

        for it in self._items:
            exp_st = it.expiry_status()
            exp_disp = f"{it.expiry_date} ({exp_st})" if it.expiry_date else "N/A"
            if it.quantity <= 0:
                flag = "OUT OF STOCK"
                tag = ("zero",)
            elif it.is_low_stock:
                flag = "LOW STOCK"
                tag = ("low",)
            else:
                flag = "OK"
                tag = ()
            self.tree.insert(
                "",
                "end",
                iid=str(it.id),
                values=(
                    it.id,
                    it.item_name,
                    it.category,
                    f"{it.quantity:g}",
                    it.unit,
                    f"{it.minimum_stock:g}",
                    flag,
                    exp_disp,
                    it.verification_status,
                    it.storage_location,
                ),
                tags=tag,
            )

        self._txs = self.tx_svc.list_transactions(self._neighbourhood.id, limit=120)
        for t in self._txs:
            route_txt = f"{t.source_location or '-'} -> {t.destination_location or '-'}"
            self.tx_tree.insert(
                "",
                "end",
                values=(
                    t.id,
                    t.transaction_type,
                    t.item_name,
                    f"{t.quantity:g} {t.unit}",
                    route_txt,
                    t.operator,
                    t.reason,
                    t.created_at,
                ),
            )

    def _clear_form(self) -> None:
        self._selected_id = None
        self.var_cat.set(INVENTORY_CATEGORIES[0])
        self._on_cat_changed()
        self.var_name.set("")
        self.var_qty.set("0")
        self.var_unit.set("litres")
        self.var_min.set("10")
        self.var_loc.set("Primary Relief Store")
        self.var_exp.set("")
        self.var_sup.set("")
        self.var_ver.set(INVENTORY_VERIFICATION_STATUSES[0])
        self.var_notes.set("")

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        iid = int(sel[0])
        it = next((x for x in self._items if x.id == iid), None)
        if it is None:
            return
        self._selected_id = it.id
        self.var_cat.set(it.category)
        self._on_cat_changed()
        self.var_name.set(it.item_name)
        self.var_qty.set(f"{it.quantity:g}")
        self.var_unit.set(it.unit)
        self.var_min.set(f"{it.minimum_stock:g}")
        self.var_loc.set(it.storage_location)
        self.var_exp.set(it.expiry_date)
        self.var_sup.set(it.supplier)
        self.var_ver.set(it.verification_status)
        self.var_notes.set(it.notes)

    def _register(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            return
        try:
            rec = self.inv_mgr.register_item(
                neighbourhood_id=self._neighbourhood.id,
                item_name=self.var_name.get(),
                category=self.var_cat.get(),
                quantity=self.var_qty.get(),
                unit=self.var_unit.get(),
                minimum_stock=self.var_min.get(),
                storage_location=self.var_loc.get(),
                expiry_date=self.var_exp.get(),
                supplier=self.var_sup.get(),
                verification_status=self.var_ver.get(),
                operator=self.var_mv_op.get(),
                notes=self.var_notes.get(),
            )
            self._selected_id = rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update_meta(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Item", "Select an existing inventory item first.")
            return
        try:
            self.inv_mgr.update_item_metadata(
                item_id=self._selected_id,
                item_name=self.var_name.get(),
                category=self.var_cat.get(),
                unit=self.var_unit.get(),
                minimum_stock=self.var_min.get(),
                storage_location=self.var_loc.get(),
                expiry_date=self.var_exp.get(),
                supplier=self.var_sup.get(),
                verification_status=self.var_ver.get(),
                notes=self.var_notes.get(),
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _delete(self) -> None:
        if self._selected_id is None:
            return
        cur = self.inv_mgr.get_item(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete inventory item '{cur.item_name}' and its transaction log?"):
            return
        self.inv_mgr.delete_item(self._selected_id)
        self._clear_form()
        self.on_data_changed()

    def _add_stock(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Item", "Select an item first.")
            return
        try:
            self.inv_mgr.add_stock(
                item_id=self._selected_id,
                amount=self.var_mv_qty.get(),
                operator=self.var_mv_op.get(),
                reason=self.var_mv_reason.get(),
                source_location=self.var_mv_loc.get(),
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Stock Error", str(exc))

    def _deduct_stock(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Item", "Select an item first.")
            return
        cur = self.inv_mgr.get_item(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno(
            "Confirm Stock Deduction",
            f"Deduct {self.var_mv_qty.get()} {cur.unit} from '{cur.item_name}' (current {cur.quantity:g})?",
        ):
            return
        try:
            self.inv_mgr.deduct_stock(
                item_id=self._selected_id,
                amount=self.var_mv_qty.get(),
                operator=self.var_mv_op.get(),
                reason=self.var_mv_reason.get(),
                destination_location=self.var_mv_loc.get() or "Field dispatch",
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Insufficient / Invalid Stock", str(exc))

    def _adjust_stock(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Item", "Select an item first.")
            return
        cur = self.inv_mgr.get_item(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno(
            "Confirm Physical Stock Adjustment",
            f"Reset count of '{cur.item_name}' from {cur.quantity:g} to {self.var_mv_qty.get()} {cur.unit}?",
        ):
            return
        try:
            self.inv_mgr.adjust_stock(
                item_id=self._selected_id,
                new_quantity=self.var_mv_qty.get(),
                operator=self.var_mv_op.get(),
                reason=self.var_mv_reason.get() or "Physical count adjustment",
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Adjustment Error", str(exc))

    def _transfer_stock(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Item", "Select an item first.")
            return
        dest = self.var_mv_loc.get().strip()
        if not dest:
            messagebox.showinfo("Destination Needed", "Enter target storage location in 'Target / Source Location'.")
            return
        try:
            _src, dest_rec = self.inv_mgr.transfer_stock(
                item_id=self._selected_id,
                amount=self.var_mv_qty.get(),
                destination_storage=dest,
                operator=self.var_mv_op.get(),
                reason=self.var_mv_reason.get() or "Storage relocation",
            )
            self._selected_id = dest_rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Transfer Error", str(exc))


class ResourceAllocationTab(tk.Frame):
    """Confirmed, atomic resource allocation workflow across inventory, vehicles, teams & volunteers."""

    def __init__(
        self,
        parent: tk.Misc,
        allocator: ResourceAllocator,
        inv_mgr: InventoryManager,
        shelter_mgr: ShelterManager,
        team_mgr: RescueTeamManager,
        vehicle_mgr: VehicleManager,
        volunteer_mgr: VolunteerManager,
        op_mgr: OperationManager,
        on_data_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.allocator = allocator
        self.inv_mgr = inv_mgr
        self.shelter_mgr = shelter_mgr
        self.team_mgr = team_mgr
        self.vehicle_mgr = vehicle_mgr
        self.volunteer_mgr = volunteer_mgr
        self.op_mgr = op_mgr
        self.on_data_changed = on_data_changed

        self._neighbourhood: Neighbourhood | None = None
        self._allocations: list[ResourceAllocationRecord] = []
        self._selected_alloc_id: int | None = None

        self._items: list[InventoryItemRecord] = []
        self._vehicles: list[VehicleRecord] = []
        self._teams: list[RescueTeamRecord] = []
        self._volunteers: list[VolunteerRecord] = []
        self._shelters: list[ShelterRecord] = []
        self._operations: list[EmergencyOperationRecord] = []

        self._res_choices: list[tuple[str, int]] = []
        self._dest_choices: list[tuple[str, int | None, str]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        banner = tk.Frame(
            self,
            bg=THEME["info_bg"],
            highlightbackground=THEME["info"],
            highlightthickness=1,
            padx=10,
            pady=5,
        )
        banner.pack(fill="x", pady=(0, 8))
        tk.Label(
            banner,
            text=(
                "ATOMIC RESOURCE ALLOCATION: Every allocation checks real SQLite availability, prompts for operator confirmation, "
                "and commits or rolls back inside one SQLite transaction."
            ),
            bg=THEME["info_bg"],
            fg="#BAE6FD",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            justify="left",
            wraplength=980,
        ).pack(anchor="w", fill="x")

        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=360,
            padx=10,
            pady=8,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_propagate(False)
        left.pack_propagate(False)

        tk.Label(
            left,
            text="NEW RESOURCE ALLOCATION",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 6))

        self.var_rtype = tk.StringVar(value=ALLOCATION_RESOURCE_TYPES[0])
        self.var_resource = tk.StringVar()
        self.var_qty = tk.StringVar(value="1")
        self.var_dtype = tk.StringVar(value="shelter")
        self.var_dest = tk.StringVar()
        self.var_dest_custom = tk.StringVar()
        self.var_op = tk.StringVar(value="None")
        self.var_operator = tk.StringVar(value="Operator")
        self.var_reason = tk.StringVar()

        tk.Label(left, text="Resource Type:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        rt_cb = ttk.Combobox(left, textvariable=self.var_rtype, values=ALLOCATION_RESOURCE_TYPES, state="readonly")
        rt_cb.pack(fill="x", pady=(0, 4))
        rt_cb.bind("<<ComboboxSelected>>", lambda _e: self._sync_resource_dropdown())

        tk.Label(left, text="Available Resource *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.res_cb = ttk.Combobox(left, textvariable=self.var_resource, state="readonly")
        self.res_cb.pack(fill="x", pady=(0, 4))

        tk.Label(left, text="Quantity (1 for vehicles/teams/volunteers):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.ent_qty = ttk.Entry(left, textvariable=self.var_qty)
        self.ent_qty.pack(fill="x", pady=(0, 4))

        tk.Label(left, text="Destination Type:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        dt_cb = ttk.Combobox(
            left,
            textvariable=self.var_dtype,
            values=("shelter", "rescue_team", "emergency_operation", "field_site"),
            state="readonly",
        )
        dt_cb.pack(fill="x", pady=(0, 4))
        dt_cb.bind("<<ComboboxSelected>>", lambda _e: self._sync_dest_dropdown())

        tk.Label(left, text="Destination Record:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.dest_cb = ttk.Combobox(left, textvariable=self.var_dest, state="readonly")
        self.dest_cb.pack(fill="x", pady=(0, 4))

        tk.Label(left, text="Custom / Field Site Label (when field_site):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        ttk.Entry(left, textvariable=self.var_dest_custom).pack(fill="x", pady=(0, 4))

        tk.Label(left, text="Link to Emergency Operation (Optional):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.op_cb = ttk.Combobox(left, textvariable=self.var_op, state="readonly")
        self.op_cb.pack(fill="x", pady=(0, 4))

        tk.Label(left, text="Authorizing Operator:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        ttk.Entry(left, textvariable=self.var_operator).pack(fill="x", pady=(0, 4))

        tk.Label(left, text="Reason / Dispatch Notes:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        ttk.Entry(left, textvariable=self.var_reason).pack(fill="x", pady=(0, 8))

        ttk.Button(
            left,
            text="Allocate Resource (Requires Confirmation)",
            style="Accent.TButton",
            command=self._allocate,
        ).pack(fill="x", pady=(2, 8))

        # Status actions for selected allocation
        tk.Label(
            left,
            text="SELECTED ALLOCATION LIFECYCLE",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(6, 4))

        st_btns = tk.Frame(left, bg=THEME["bg_card"])
        st_btns.pack(fill="x")
        st_btns.columnconfigure(0, weight=1)
        st_btns.columnconfigure(1, weight=1)
        ttk.Button(st_btns, text="Mark Dispatched", command=lambda: self._update_status("Dispatched")).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(st_btns, text="Mark Delivered", command=lambda: self._update_status("Delivered")).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(st_btns, text="Mark Returned", command=lambda: self._update_status("Returned")).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(st_btns, text="Cancel & Rollback", command=lambda: self._update_status("Cancelled")).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # Right side table
        right = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        filt = tk.Frame(right, bg=THEME["bg_card"])
        filt.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(filt, text="Status Filter:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_filter = tk.StringVar(value="All")
        cb_f = ttk.Combobox(
            filt,
            textvariable=self.var_filter,
            values=("All", "Allocated", "Dispatched", "Delivered", "Returned", "Cancelled"),
            state="readonly",
            width=13,
        )
        cb_f.pack(side="left", padx=(4, 8))
        cb_f.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.summary_lbl = tk.Label(filt, text="0 allocation(s)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.summary_lbl.pack(side="right")

        cols = ("id", "rtype", "res", "qty", "dest", "op", "status", "operator", "ts")
        wrap = tk.Frame(right, bg=THEME["bg_card"])
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for k, h, w in [
            ("id", "ID", 38),
            ("rtype", "Type", 100),
            ("res", "Allocated Resource", 160),
            ("qty", "Qty", 55),
            ("dest", "Destination", 150),
            ("op", "Operation", 125),
            ("status", "Status", 88),
            ("operator", "Operator", 85),
            ("ts", "Created UTC", 130),
        ]:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="e" if k in ("id", "qty") else "w")
        vsb_t = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_t.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb_t.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        if (neighbourhood.id if neighbourhood else None) != (self._neighbourhood.id if self._neighbourhood else None):
            self._selected_alloc_id = None
        self._neighbourhood = neighbourhood
        self.refresh()

    def refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._allocations = []
            self.summary_lbl.configure(text="No active workspace")
            return

        nid = self._neighbourhood.id
        self._items = self.inv_mgr.list_items(nid)
        self._vehicles = self.vehicle_mgr.list_vehicles(nid)
        self._teams = self.team_mgr.list_teams(nid)
        self._volunteers = self.volunteer_mgr.list_volunteers(nid)
        self._shelters = self.shelter_mgr.list_shelters(nid)
        self._operations = self.op_mgr.list_operations(nid)

        op_vals = ["None"] + [
            f"#{o.id}: {o.operation_name}" for o in self._operations if o.status not in ("Completed", "Cancelled")
        ]
        self.op_cb.configure(values=op_vals)
        if self.var_op.get() not in op_vals:
            self.var_op.set("None")

        self._sync_resource_dropdown()
        self._sync_dest_dropdown()

        self._allocations = self.allocator.list_allocations(nid, status_filter=self.var_filter.get())
        self.summary_lbl.configure(text=f"{len(self._allocations)} allocation(s)")
        for a in self._allocations:
            self.tree.insert(
                "",
                "end",
                iid=str(a.id),
                values=(
                    a.id,
                    a.resource_type,
                    a.resource_label,
                    f"{a.quantity:g}",
                    a.destination_label,
                    a.operation_name or "None",
                    a.status,
                    a.operator,
                    a.created_at,
                ),
            )

    def _sync_resource_dropdown(self) -> None:
        rt = self.var_rtype.get()
        choices: list[tuple[str, int]] = []
        if rt == "inventory_item":
            for i in self._items:
                if i.id is not None:
                    choices.append((f"#{i.id}: {i.item_name} ({i.quantity:g} {i.unit})", i.id))
            self.ent_qty.configure(state="normal")
        else:
            self.var_qty.set("1")
            self.ent_qty.configure(state="disabled")
            if rt == "vehicle":
                for v in self._vehicles:
                    if v.id is not None and v.operational_status == "Available":
                        choices.append((f"#{v.id}: {v.registration_number} ({v.vehicle_type})", v.id))
            elif rt == "rescue_team":
                for t in self._teams:
                    if t.id is not None and t.availability == "Available":
                        choices.append((f"#{t.id}: {t.team_name}", t.id))
            elif rt == "volunteer":
                for vo in self._volunteers:
                    if vo.id is not None and vo.availability == "Available":
                        choices.append((f"#{vo.id}: {vo.name} ({vo.skills or 'General'})", vo.id))

        self._res_choices = choices
        lbls = [c[0] for c in choices]
        self.res_cb.configure(values=lbls)
        if lbls and self.var_resource.get() not in lbls:
            self.var_resource.set(lbls[0])
        elif not lbls:
            self.var_resource.set("No available records for type")

    def _sync_dest_dropdown(self) -> None:
        dt = self.var_dtype.get()
        choices: list[tuple[str, int | None, str]] = []
        if dt == "shelter":
            for s in self._shelters:
                if s.id is not None:
                    choices.append((f"#{s.id}: {s.name} ({s.status})", s.id, s.name))
        elif dt == "rescue_team":
            for t in self._teams:
                if t.id is not None:
                    choices.append((f"#{t.id}: {t.team_name}", t.id, t.team_name))
        elif dt == "emergency_operation":
            for o in self._operations:
                if o.id is not None:
                    choices.append((f"#{o.id}: {o.operation_name}", o.id, o.operation_name))
        else:
            choices.append(("Custom Field Site (Enter label below)", None, ""))

        self._dest_choices = choices
        lbls = [c[0] for c in choices]
        self.dest_cb.configure(values=lbls)
        if lbls and self.var_dest.get() not in lbls:
            self.var_dest.set(lbls[0])

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if sel:
            self._selected_alloc_id = int(sel[0])

    def _allocate(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            return
        res_lbl = self.var_resource.get()
        res_id = next((rid for lbl, rid in self._res_choices if lbl == res_lbl), None)
        if res_id is None:
            messagebox.showinfo("Resource Required", "No available resource selected.")
            return

        dtype = self.var_dtype.get()
        dest_id: int | None = None
        dest_label = self.var_dest_custom.get().strip()
        if dtype != "field_site":
            d_sel = self.var_dest.get()
            hit = next(((did, dlbl) for lbl, did, dlbl in self._dest_choices if lbl == d_sel), None)
            if hit is not None:
                dest_id, rec_lbl = hit
                if not dest_label:
                    dest_label = rec_lbl
        if not dest_label:
            messagebox.showinfo("Destination Required", "Select a destination or enter a custom destination label.")
            return

        op_id: int | None = None
        op_sel = self.var_op.get()
        if op_sel.startswith("#"):
            try:
                op_id = int(op_sel.split(":", 1)[0][1:])
            except ValueError:
                op_id = None

        qty_txt = self.var_qty.get()
        if not messagebox.askyesno(
            "Confirm Resource Allocation",
            f"Allocate {qty_txt} of [{self.var_rtype.get()}] '{res_lbl}'\n"
            f"Destination ({dtype}): {dest_label}\n\n"
            "Proceed with atomic SQLite transaction?",
        ):
            return

        try:
            rec = self.allocator.allocate_resource(
                neighbourhood_id=self._neighbourhood.id,
                resource_type=self.var_rtype.get(),
                resource_id=res_id,
                destination_type=dtype,
                destination_id=dest_id,
                destination_label=dest_label,
                quantity=qty_txt,
                operation_id=op_id,
                reason=self.var_reason.get(),
                operator=self.var_operator.get() or "Operator",
            )
            self._selected_alloc_id = rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Allocation Blocked / Rolled Back", str(exc))

    def _update_status(self, next_status: str) -> None:
        if self._selected_alloc_id is None:
            messagebox.showinfo("Select Allocation", "Select an allocation row first.")
            return
        if next_status in ("Returned", "Cancelled"):
            if not messagebox.askyesno(
                f"Confirm {next_status}",
                f"Mark Allocation #{self._selected_alloc_id} as '{next_status}' and restore stock / release asset?",
            ):
                return
        try:
            self.allocator.update_allocation_status(
                allocation_id=self._selected_alloc_id,
                new_status=next_status,
                operator=self.var_operator.get() or "Operator",
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Status Error", str(exc))

import tkinter as tk
from tkinter import ttk
from typing import Optional, Literal, Any, Union, List

from pydantic import BaseModel


class FormFieldBase(BaseModel):
    key: str
    title: str
    placeholder: Optional[str] = None
    shown: bool = True
    type: Literal["text", "bool", "select"]
    default_value: Optional[Any] = None


class FormFieldText(FormFieldBase):
    type: Literal["text"] = "text"
    default_value: Optional[str] = None


class FormFieldBool(FormFieldBase):
    type: Literal["bool"] = "bool"
    default_value: Optional[bool] = False


class FormFieldSelect(FormFieldBase):
    type: Literal["select"] = "select"
    options: list[str]
    default_value: Optional[str] = None


FormField = Union[FormFieldText, FormFieldBool, FormFieldSelect]


class FormSection(BaseModel):
    title: str
    fields: List[FormField]


class DialogForm(BaseModel):
    title: str
    sections: List[FormSection]
    submit_button_text: str = "Submit"


def show_dialog_form(dialog_form: DialogForm):
    class DialogFormWindow(tk.Toplevel):
        def __init__(self, parent, dialog_form):
            super().__init__(parent)
            self.transient(parent)
            self.grab_set()
            self.title(dialog_form.title)
            self.result = None
            self.widgets = {}
            row = 0
            for section in dialog_form.sections:
                tk.Label(self, text=section.title, font=("Arial", 10, "bold")).grid(row=row, column=0, columnspan=2,
                                                                                    sticky="w", pady=(10, 2))
                row += 1
                for field in section.fields:
                    if not field.shown:
                        continue
                    tk.Label(self, text=field.title).grid(row=row, column=0, padx=5, pady=5, sticky="w")
                    if field.type == "text":
                        entry = tk.Entry(self)
                        if field.default_value is not None:
                            entry.insert(0, field.default_value)
                        entry.grid(row=row, column=1, padx=5, pady=5)
                        self.widgets[field.key] = entry
                    elif field.type == "bool":
                        var = tk.BooleanVar(value=field.default_value if field.default_value is not None else False)
                        cb = tk.Checkbutton(self, variable=var)
                        cb.grid(row=row, column=1, padx=5, pady=5)
                        self.widgets[field.key] = var
                    elif field.type == "select":
                        combo = ttk.Combobox(self, values=field.options)
                        if field.default_value is not None:
                            combo.set(field.default_value)
                        combo.grid(row=row, column=1, padx=5, pady=5)
                        self.widgets[field.key] = combo
                    row += 1
            submit_btn = tk.Button(self, text=dialog_form.submit_button_text, command=self.on_submit)
            submit_btn.grid(row=row, column=0, columnspan=2, pady=10)
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            self.deiconify()
            self.focus_force()

        def on_submit(self):
            values = {}
            for section in dialog_form.sections:
                for field in section.fields:
                    if not field.shown:
                        continue
                    widget = self.widgets[field.key]
                    if field.type == "text":
                        values[field.key] = widget.get()
                    elif field.type == "bool":
                        values[field.key] = widget.get()
                    elif field.type == "select":
                        values[field.key] = widget.get()
            self.result = values
            self.destroy()

        def on_close(self):
            self.result = None
            self.destroy()

    root = tk.Tk()
    # root.overrideredirect(True)
    # root.attributes("-alpha", 0)
    win = DialogFormWindow(root, dialog_form)
    root.wait_window(win)
    root.destroy()
    return win.result
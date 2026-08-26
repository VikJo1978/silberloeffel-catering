from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing anchor in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


def replace_span(path: str, start: str, end: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text()
    start_pos = text.find(start)
    if start_pos < 0:
        raise SystemExit(f"missing start marker in {path}: {start!r}")
    end_pos = text.find(end, start_pos)
    if end_pos < 0:
        raise SystemExit(f"missing end marker in {path}: {end!r}")
    p.write_text(text[:start_pos] + replacement + text[end_pos:])


# Core Office API
api = "src/catering_system/ui/office_api.py"
replace_once(
    api,
    "from urllib.parse import parse_qsl, unquote, urlparse\n",
    "from urllib.parse import parse_qsl, quote, unquote, urlparse\n",
)
replace_once(
    api,
    "    validate_manual_task_subject_type,\n)",
    "    validate_manual_task_priority,\n    validate_manual_task_subject_type,\n)",
)
replace_once(
    api,
    "from catering_system.services.contact_projection_service import ContactProjectionService\n",
    "from catering_system.services.contact_profile_service import ContactProfileService\n"
    "from catering_system.services.contact_projection_service import ContactProjectionService\n",
)
replace_once(
    api,
    '        "subject_id": task.subject_id,\n    }\n',
    '        "subject_id": task.subject_id,\n        "priority": task.priority,\n    }\n',
)
replace_once(
    api,
    "        self.chat_service = ChatService(\n"
    "            self.chat,\n"
    "            self.employee_auth_repository,\n"
    "            orders=self.orders,\n"
    "            inquiries=self.inquiries,\n"
    "            contacts=self.contact_profiles,\n"
    "        )\n"
    "        self.manual_task_service = ManualTaskService(\n",
    "        self.chat_service = ChatService(\n"
    "            self.chat,\n"
    "            self.employee_auth_repository,\n"
    "            orders=self.orders,\n"
    "            inquiries=self.inquiries,\n"
    "            contacts=self.contact_profiles,\n"
    "        )\n"
    "        self.contact_profile_service = ContactProfileService(self.contact_profiles)\n"
    "        self.manual_task_service = ManualTaskService(\n",
)
replace_once(
    api,
    '        if subject_type == "INQUIRY":\n'
    "            return self.inquiries.get_by_id(subject_id) is not None\n"
    '        if subject_type == "CONTACT":\n',
    '        if subject_type == "INQUIRY":\n'
    "            return self.inquiries.get_by_id(subject_id) is not None\n"
    '        if subject_type == "OFFER":\n'
    "            return self.offers.get(subject_id) is not None\n"
    '        if subject_type == "CONTACT":\n',
)

subject_method = '''    def manual_task_subjects(
        self, employee: AuthenticatedEmployee
    ) -> dict[str, object]:
        permissions = employee.effective_permissions
        inquiries = self.inquiries.list_all()
        inquiries_by_id = {inquiry.inquiry_id: inquiry for inquiry in inquiries}
        rows: list[dict[str, object]] = []

        def inquiry_label(inquiry) -> str:
            snapshot = inquiry.customer_snapshot
            customer = None
            if snapshot is not None:
                customer = snapshot.company_name or snapshot.contact_name
            primary = (
                customer
                or inquiry.intake_subject
                or inquiry.location_text
                or f"Anfrage {inquiry.inquiry_id[:8]}"
            )
            return f"{primary} · {inquiry.event_date.isoformat()}"

        if "customers.view" in permissions:
            contacts = sorted(
                self.contact_projection_service.list_contacts(),
                key=lambda contact: (contact.display_name.casefold(), contact.contact_key),
            )
            for contact in contacts:
                rows.append(
                    {
                        "subject_type": "CONTACT",
                        "subject_id": self.contact_profile_service.find_by_alias(
                            "contact_key", contact.contact_key
                        ),
                        "contact_key": contact.contact_key,
                        "label": f"Kontakt · {contact.display_name}",
                        "href": f"/kontakt/{quote(contact.contact_key, safe='')}",
                    }
                )
        if "inquiries.view" in permissions:
            for inquiry in sorted(
                inquiries, key=lambda item: (item.event_date, item.inquiry_id)
            ):
                rows.append(
                    {
                        "subject_type": "INQUIRY",
                        "subject_id": inquiry.inquiry_id,
                        "contact_key": None,
                        "label": f"Anfrage · {inquiry_label(inquiry)}",
                        "href": f"/inquiry/{inquiry.inquiry_id}",
                    }
                )
        if "offers.view" in permissions:
            for offer in self.offers.list_all():
                inquiry = inquiries_by_id.get(offer.source_inquiry_id)
                suffix = (
                    inquiry_label(inquiry) if inquiry is not None else offer.offer_id[:8]
                )
                rows.append(
                    {
                        "subject_type": "OFFER",
                        "subject_id": offer.offer_id,
                        "contact_key": None,
                        "label": f"Angebot · {suffix}",
                        "href": f"/offer/{offer.offer_id}",
                    }
                )
        if "orders.view" in permissions:
            for order in self.orders.list_orders():
                inquiry = inquiries_by_id.get(order.source_inquiry_id)
                suffix = (
                    inquiry_label(inquiry) if inquiry is not None else order.order_id[:8]
                )
                rows.append(
                    {
                        "subject_type": "ORDER",
                        "subject_id": order.order_id,
                        "contact_key": None,
                        "label": f"Auftrag · {suffix}",
                        "href": f"/order/{order.order_id}",
                    }
                )
        rows.sort(
            key=lambda row: (
                str(row["subject_type"]),
                str(row["label"]).casefold(),
            )
        )
        return {"subjects": rows}

'''
replace_once(
    api,
    "    def list_calendar(self, from_date: date, to_date: date) -> dict[str, object]:\n",
    subject_method
    + "    def list_calendar(self, from_date: date, to_date: date) -> dict[str, object]:\n",
)

create_manual = '''    def cmd_create_manual_task(
        self, path_ids: dict[str, str], args: dict[str, object], expect: dict
    ) -> tuple[int, dict[str, object]]:
        employee = self._require_active_employee()
        subject_type = _v_enum(
            args.get("subject_type", "NONE"), validate_manual_task_subject_type
        )
        assigned_to_employee_id = _v_optional_uuid4(args.get("assigned_to_employee_id"))
        subject_id = _v_optional_uuid4(args.get("subject_id"))
        subject_contact_key = _v_optional_str(args.get("subject_contact_key"), 1000)
        if subject_type == "CONTACT" and subject_contact_key is not None:
            if subject_id is not None:
                raise _invalid()
            projection = self.contact_projection_service.contact_detail(subject_contact_key)
            if projection is None:
                raise _invalid()
            subject_id = self.contact_profile_service.ensure_for_projection(projection.contact)
        elif subject_contact_key is not None:
            raise _invalid()
        try:
            task = self.manual_task_service.create_task(
                title=_v_str(args["title"], 200),
                description=_v_optional_str(args.get("description"), 4000) or "",
                due_at=_v_optional_datetime(args.get("due_at")),
                created_by_employee_id=employee.account.id,
                assigned_to_employee_id=assigned_to_employee_id,
                subject_type=subject_type,
                subject_id=subject_id,
                priority=_v_enum(
                    args.get("priority", "NORMAL"), validate_manual_task_priority
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ApiError(422, "invalid_request") from exc
        except (TypeError, ValueError) as exc:
            raise _invalid() from exc
        return 201, {"manual_task": _manual_task_shape(task)}

'''
replace_span(
    api,
    "    def cmd_create_manual_task(\n",
    "    def cmd_complete_manual_task(\n",
    create_manual,
)
replace_once(
    api,
    '            "subject_type",\n            "subject_id",\n',
    '            "subject_type",\n'
    '            "subject_id",\n'
    '            "subject_contact_key",\n'
    '            "priority",\n',
)
replace_once(
    api,
    '    (\n        re.compile(r"^/office/v1/manual-tasks$"),\n',
    '    (\n'
    '        re.compile(r"^/office/v1/manual-task-subjects$"),\n'
    '        "/office/v1/manual-task-subjects",\n'
    '        {"GET": "list_manual_task_subjects"},\n'
    '    ),\n'
    '    (\n'
    '        re.compile(r"^/office/v1/manual-tasks$"),\n',
)
replace_once(
    api,
    '            if kind == "list_manual_tasks":\n'
    '                return self._employee_with_permission("tasks.view")\n',
    '            if kind in {"list_manual_tasks", "list_manual_task_subjects"}:\n'
    '                return self._employee_with_permission("tasks.view")\n',
)
replace_once(
    api,
    "                if (\n"
    "                    args is not None\n"
    '                    and args.get("assigned_to_employee_id") is not None\n'
    '                    and "tasks.assign" not in employee.effective_permissions\n'
    "                ):\n"
    '                    raise ApiError(403, "forbidden")\n'
    "                return employee\n",
    "                if (\n"
    "                    args is not None\n"
    '                    and args.get("assigned_to_employee_id") is not None\n'
    '                    and "tasks.assign" not in employee.effective_permissions\n'
    "                ):\n"
    '                    raise ApiError(403, "forbidden")\n'
    "                subject_permission = {\n"
    '                    "CONTACT": "customers.view",\n'
    '                    "INQUIRY": "inquiries.view",\n'
    '                    "OFFER": "offers.view",\n'
    '                    "ORDER": "orders.view",\n'
    '                }.get(str((args or {}).get("subject_type", "NONE")))\n'
    "                if (\n"
    "                    subject_permission is not None\n"
    "                    and subject_permission not in employee.effective_permissions\n"
    "                ):\n"
    '                    raise ApiError(403, "forbidden")\n'
    "                return employee\n",
)
replace_once(
    api,
    '            elif kind == "list_manual_tasks":\n',
    '            elif kind == "list_manual_task_subjects":\n'
    "                self._query(set())\n"
    "                employee = self._manual_task_employee(kind)\n"
    "                self._respond(200, api.manual_task_subjects(employee))\n"
    '            elif kind == "list_manual_tasks":\n',
)

# RemoteCoreClient
remote = "src/catering_system/ui/remote_core_client.py"
replace_once(
    remote,
    "    validate_manual_task,\n    validate_manual_task_subject_type,\n)",
    "    validate_manual_task,\n"
    "    validate_manual_task_priority,\n"
    "    validate_manual_task_subject_type,\n)",
)
manual_parser = '''def _manual_task(value: object) -> ManualTask:
    data = _dict(value)
    _exact(
        data,
        {
            "task_id",
            "title",
            "description",
            "due_at",
            "status",
            "created_at",
            "completed_at",
            "created_by_employee_id",
            "assigned_to_employee_id",
            "subject_type",
            "subject_id",
            "priority",
        },
    )
    try:
        task = validate_manual_task(
            ManualTask(
                task_id=_uuid4(data["task_id"]),
                title=_str(data["title"]),
                description=_str(data["description"]),
                due_at=_optional_datetime(data["due_at"]),
                created_at=_datetime(data["created_at"]),
                completed_at=_optional_datetime(data["completed_at"]),
                created_by_employee_id=_uuid4(data["created_by_employee_id"]),
                assigned_to_employee_id=_optional_uuid4(
                    data["assigned_to_employee_id"]
                ),
                subject_type=validate_manual_task_subject_type(
                    _str(data["subject_type"])
                ),
                subject_id=_optional_uuid4(data["subject_id"]),
                priority=validate_manual_task_priority(_str(data["priority"])),
            )
        )
    except (TypeError, ValueError):
        _bad_response()
    if _str(data["status"]) != task.status:
        _bad_response()
    return task


'''
replace_span(
    remote,
    "def _manual_task(value: object) -> ManualTask:\n",
    "_CHAT_THREAD_KEYS =",
    manual_parser,
)
manual_methods = '''    def list_manual_tasks(
        self,
        *,
        employee_session_token: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> list[ManualTask]:
        query: dict[str, object] | None = None
        if subject_type is not None or subject_id is not None:
            if subject_type is None or subject_id is None:
                raise ValueError("subject_type and subject_id must be paired")
            query = {"subject_type": subject_type, "subject_id": subject_id}
        body = self.get(
            "/office/v1/manual-tasks",
            query=query,
            employee_session_token=employee_session_token,
        )
        _exact(body, {"manual_tasks"})
        return [_manual_task(raw) for raw in _list(body["manual_tasks"])]

    def list_manual_task_subjects(
        self, *, employee_session_token: str
    ) -> list[dict[str, object]]:
        body = self.get(
            "/office/v1/manual-task-subjects",
            employee_session_token=employee_session_token,
        )
        _exact(body, {"subjects"})
        results: list[dict[str, object]] = []
        for raw in _list(body["subjects"]):
            row = _dict(raw)
            _exact(
                row,
                {"subject_type", "subject_id", "contact_key", "label", "href"},
            )
            subject_type = _str(row["subject_type"])
            if subject_type not in {"CONTACT", "INQUIRY", "OFFER", "ORDER"}:
                _bad_response()
            subject_id = _optional_uuid4(row["subject_id"])
            contact_key = _optional_str(row["contact_key"])
            label = _str(row["label"])
            href = _str(row["href"])
            if subject_type == "CONTACT":
                if contact_key is None:
                    _bad_response()
            elif subject_id is None or contact_key is not None:
                _bad_response()
            results.append(
                {
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "contact_key": contact_key,
                    "label": label,
                    "href": href,
                }
            )
        return results

    def create_manual_task(
        self,
        *,
        employee_session_token: str,
        title: str,
        description: str | None = None,
        due_at: datetime | None = None,
        assigned_to_employee_id: str | None = None,
        subject_type: str = "NONE",
        subject_id: str | None = None,
        subject_contact_key: str | None = None,
        priority: str = "NORMAL",
        command_id: str | None = None,
    ) -> ManualTask:
        result = self.command(
            "/office/v1/manual-tasks",
            args={
                "title": title,
                "description": description,
                "due_at": due_at.isoformat() if due_at is not None else None,
                "assigned_to_employee_id": assigned_to_employee_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "subject_contact_key": subject_contact_key,
                "priority": priority,
            },
            expect={},
            expected={201},
            result_keys={"manual_task"},
            command_id=command_id,
            employee_session_token=employee_session_token,
        )
        return _manual_task(result["manual_task"])

    def complete_manual_task(
        self,
        task_id: str,
        *,
        employee_session_token: str,
        command_id: str | None = None,
    ) -> ManualTask:
        result = self.command(
            f"/office/v1/manual-tasks/{quote(task_id, safe='')}/complete",
            args={},
            expect={},
            expected={200},
            result_keys={"manual_task"},
            command_id=command_id,
            employee_session_token=employee_session_token,
        )
        return _manual_task(result["manual_task"])

'''
replace_span(
    remote,
    "    def list_manual_tasks(\n",
    "    def create_chat_thread(\n",
    manual_methods,
)

# OfficePanel
panel = "src/catering_system/ui/office_panel.py"
replace_once(
    panel,
    "from catering_system.ui.office_panel_calendar_list import render_kalender_list\n",
    "from catering_system.ui.manual_task_presentation import (\n"
    "    make_subject_reference,\n"
    "    parse_subject_reference,\n"
    "    priority_label,\n"
    "    sort_task_rows,\n"
    "    system_task_priority,\n"
    ")\n"
    "from catering_system.ui.office_panel_calendar_list import render_kalender_list\n",
)
task_block = '''    def _task_list_rows(self) -> list[dict[str, object]]:
        if self._remote is not None:
            body = self._remote.list_tasks()
            rows = cast(list[dict[str, object]], body["tasks"])
        else:
            rows = api_views.task_list_view(
                self._task_projection_service().list_tasks()
            )
        return [self._system_task_row(row) for row in rows]

    def _system_task_row(self, row: dict[str, object]) -> dict[str, object]:
        priority = system_task_priority(row)
        return {
            **row,
            "kind": "system",
            "type_label": "System",
            "assigned_to": "–",
            "priority": priority,
            "priority_label": priority_label(priority),
            "description": "–",
            "subject_label": str(row.get("subtitle") or "–"),
            "subject_href": str(row.get("action_href") or ""),
        }

    def _manual_tasks(self, *, employee_session_token: str | None) -> list[ManualTask]:
        if self._remote is not None:
            if not employee_session_token:
                return []
            return self._remote.list_manual_tasks(
                employee_session_token=employee_session_token
            )
        if self._manual_task_service is None:
            return []
        return self._manual_task_service.list_open_tasks()

    @staticmethod
    def _manual_subject_label(prefix: str, inquiry: Inquiry | None, fallback: str) -> str:
        if inquiry is None:
            return f"{prefix} · {fallback[:8]}"
        snapshot = inquiry.customer_snapshot
        customer = None
        if snapshot is not None:
            customer = snapshot.company_name or snapshot.contact_name
        primary = (
            customer
            or inquiry.intake_subject
            or inquiry.location_text
            or fallback[:8]
        )
        return f"{prefix} · {primary} · {inquiry.event_date.isoformat()}"

    def _manual_task_subject_options(
        self,
        *,
        context: OfficePageContext,
        employee_session_token: str | None,
    ) -> list[dict[str, object]]:
        if self._remote is not None:
            if not employee_session_token:
                return []
            rows = self._remote.list_manual_task_subjects(
                employee_session_token=employee_session_token
            )
            for row in rows:
                subject_type = str(row["subject_type"])
                key = (
                    row.get("contact_key")
                    if subject_type == "CONTACT"
                    else row.get("subject_id")
                )
                if key is None:
                    continue
                row["value"] = make_subject_reference(subject_type, str(key))
            return [row for row in rows if row.get("value")]

        options: list[dict[str, object]] = []
        inquiries = self._inquiries.list_all()
        inquiries_by_id = {inquiry.inquiry_id: inquiry for inquiry in inquiries}
        if context.can("customers.view"):
            for row in self._contact_list_rows():
                contact_key = str(row["contact_key"])
                options.append(
                    {
                        "value": make_subject_reference("CONTACT", contact_key),
                        "subject_type": "CONTACT",
                        "subject_id": self.contact_profile_service.find_by_alias(
                            "contact_key", contact_key
                        ),
                        "contact_key": contact_key,
                        "label": f"Kontakt · {row['display_name']}",
                        "href": f"/kontakt/{quote(contact_key, safe='')}",
                    }
                )
        if context.can("inquiries.view"):
            for inquiry in inquiries:
                options.append(
                    {
                        "value": make_subject_reference("INQUIRY", inquiry.inquiry_id),
                        "subject_type": "INQUIRY",
                        "subject_id": inquiry.inquiry_id,
                        "contact_key": None,
                        "label": self._manual_subject_label(
                            "Anfrage", inquiry, inquiry.inquiry_id
                        ),
                        "href": f"/inquiry/{inquiry.inquiry_id}",
                    }
                )
        if context.can("offers.view"):
            for offer in self._offers.list_all():
                options.append(
                    {
                        "value": make_subject_reference("OFFER", offer.offer_id),
                        "subject_type": "OFFER",
                        "subject_id": offer.offer_id,
                        "contact_key": None,
                        "label": self._manual_subject_label(
                            "Angebot",
                            inquiries_by_id.get(offer.source_inquiry_id),
                            offer.offer_id,
                        ),
                        "href": f"/offer/{offer.offer_id}",
                    }
                )
        if context.can("orders.view"):
            for order in self._orders.list_orders():
                options.append(
                    {
                        "value": make_subject_reference("ORDER", order.order_id),
                        "subject_type": "ORDER",
                        "subject_id": order.order_id,
                        "contact_key": None,
                        "label": self._manual_subject_label(
                            "Auftrag",
                            inquiries_by_id.get(order.source_inquiry_id),
                            order.order_id,
                        ),
                        "href": f"/order/{order.order_id}",
                    }
                )
        options.sort(
            key=lambda option: (
                str(option["subject_type"]),
                str(option["label"]).casefold(),
            )
        )
        return options

    def _manual_task_rows(
        self,
        *,
        context: OfficePageContext,
        employee_session_token: str | None,
        assignee_names: dict[str, str],
        subject_options: list[dict[str, object]],
        can_complete: bool,
    ) -> list[dict[str, object]]:
        subjects = {
            (str(option["subject_type"]), str(option["subject_id"])): option
            for option in subject_options
            if option.get("subject_id") is not None
        }
        rows: list[dict[str, object]] = []
        for task in self._manual_tasks(employee_session_token=employee_session_token):
            assigned_to = "–"
            if task.assigned_to_employee_id is not None:
                assigned_to = assignee_names.get(
                    task.assigned_to_employee_id, task.assigned_to_employee_id
                )
            subject = subjects.get((task.subject_type, str(task.subject_id)))
            if task.subject_type == "NONE":
                subject_label = "–"
                subject_href = ""
            elif subject is not None:
                subject_label = str(subject["label"])
                subject_href = str(subject["href"])
            else:
                subject_label = {
                    "CONTACT": "Kontakt",
                    "INQUIRY": "Anfrage",
                    "OFFER": "Angebot",
                    "ORDER": "Auftrag",
                }.get(task.subject_type, "Bezug")
                subject_href = ""
            subtitle_parts = [
                part
                for part in (
                    task.description.strip(),
                    subject_label if subject_label != "–" else "",
                )
                if part
            ]
            rows.append(
                {
                    "kind": "manual",
                    "type_label": "Manuell",
                    "category": "manual",
                    "urgency": "normal",
                    "priority": task.priority,
                    "priority_label": priority_label(task.priority),
                    "title": task.title,
                    "description": task.description or "–",
                    "subtitle": " · ".join(subtitle_parts) or "Manuelle Aufgabe",
                    "subject_label": subject_label,
                    "subject_href": subject_href,
                    "due_at": task.due_at,
                    "opened_at": task.created_at,
                    "created_at": task.created_at,
                    "assigned_to": assigned_to,
                    "task_id": task.task_id,
                    "entity_type": (
                        task.subject_type.lower()
                        if task.subject_type in {"ORDER", "INQUIRY", "OFFER"}
                        else "manual"
                    ),
                    "entity_id": task.subject_id or task.task_id,
                    "action_href": subject_href or "/aufgaben",
                    "action_label": (
                        "Bezug öffnen" if subject_href else "Aufgaben öffnen"
                    ),
                    "can_complete": can_complete,
                    "complete_form_fields": _csrf_input(context)
                    + self._command_fields(),
                }
            )
        return rows

    def _combined_task_rows(
        self,
        *,
        context: OfficePageContext,
        employee_session_token: str | None,
        assignee_names: dict[str, str] | None = None,
        subject_options: list[dict[str, object]] | None = None,
        can_complete: bool = False,
    ) -> list[dict[str, object]]:
        rows = self._task_list_rows()
        if context.can("tasks.view") and context.employee_account_id:
            options = subject_options
            if options is None:
                options = self._manual_task_subject_options(
                    context=context,
                    employee_session_token=employee_session_token,
                )
            rows.extend(
                self._manual_task_rows(
                    context=context,
                    employee_session_token=employee_session_token,
                    assignee_names=assignee_names or {},
                    subject_options=options,
                    can_complete=can_complete,
                )
            )
        return sort_task_rows(rows)

    def render_aufgaben(
        self,
        *,
        context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
        employee_session_token: str | None = None,
        assignee_options: list[dict[str, str]] | None = None,
        subject_options: list[dict[str, object]] | None = None,
    ) -> str:
        assignee_options = assignee_options or []
        assignee_names = {
            option["id"]: option["display_name"] for option in assignee_options
        }
        if subject_options is None:
            subject_options = self._manual_task_subject_options(
                context=context,
                employee_session_token=employee_session_token,
            )
        rows = self._combined_task_rows(
            context=context,
            employee_session_token=employee_session_token,
            assignee_names=assignee_names,
            subject_options=subject_options,
            can_complete=context.can("tasks.complete")
            and bool(context.employee_account_id),
        )
        return render_aufgaben_list(
            rows,
            context=context,
            assignee_options=assignee_options,
            subject_options=[
                {"value": str(option["value"]), "label": str(option["label"])}
                for option in subject_options
            ],
            can_create_manual_task=context.can("tasks.create")
            and bool(context.employee_account_id),
            can_assign_manual_task=context.can("tasks.assign"),
            create_form_fields=_csrf_input(context) + self._command_fields(),
        )

    @staticmethod
    def _manual_task_due_at_from_form(form: dict[str, str]) -> datetime | None:
        raw = form.get("due_date", "").strip()
        if not raw:
            return None
        selected = date.fromisoformat(raw)
        berlin_start = datetime.combine(selected, time.min, tzinfo=_BERLIN)
        return berlin_start.astimezone(UTC)

    def create_manual_task(
        self,
        form: dict[str, str],
        *,
        created_by_employee_id: str,
        employee_session_token: str | None = None,
    ) -> ManualTask:
        assigned_to_employee_id: str | None = form.get(
            "assigned_to_employee_id", ""
        ).strip()
        if not assigned_to_employee_id:
            assigned_to_employee_id = None
        due_at = self._manual_task_due_at_from_form(form)
        subject_type, subject_key = parse_subject_reference(
            form.get("subject_reference", "")
        )
        subject_id: str | None = None
        subject_contact_key: str | None = None
        if subject_type == "CONTACT":
            assert subject_key is not None
            if self._remote is not None:
                subject_contact_key = subject_key
            else:
                contact_row = next(
                    (
                        row
                        for row in self._contact_list_rows()
                        if str(row["contact_key"]) == subject_key
                    ),
                    None,
                )
                if contact_row is None:
                    raise ValueError("manual task contact subject not found")
                subject_id = self._ensure_profile_for_contact_row(contact_row)
        elif subject_type != "NONE":
            subject_id = subject_key
        priority = form.get("priority", "NORMAL").strip() or "NORMAL"
        if self._remote is not None:
            if not employee_session_token:
                raise ValueError("employee session is required")
            return self._remote.create_manual_task(
                employee_session_token=employee_session_token,
                title=form.get("title", ""),
                description=form.get("description", ""),
                due_at=due_at,
                assigned_to_employee_id=assigned_to_employee_id,
                subject_type=subject_type,
                subject_id=subject_id,
                subject_contact_key=subject_contact_key,
                priority=priority,
                command_id=form.get("_command_id") or None,
            )
        if self._manual_task_service is None:
            raise ValueError("manual tasks are not available")
        return self._manual_task_service.create_task(
            title=form.get("title", ""),
            description=form.get("description", ""),
            due_at=due_at,
            created_by_employee_id=created_by_employee_id,
            assigned_to_employee_id=assigned_to_employee_id,
            subject_type=subject_type,
            subject_id=subject_id,
            priority=priority,
        )

    def complete_manual_task(
        self,
        task_id: str,
        *,
        employee_session_token: str | None = None,
    ) -> ManualTask:
        if self._remote is not None:
            if not employee_session_token:
                raise ValueError("employee session is required")
            return self._remote.complete_manual_task(
                task_id,
                employee_session_token=employee_session_token,
                command_id=self._remote.form_value("_command_id"),
            )
        if self._manual_task_service is None:
            raise ValueError("manual tasks are not available")
        return self._manual_task_service.complete_task(task_id)

'''
replace_span(
    panel,
    "    def _task_list_rows(self) -> list[dict[str, object]]:\n",
    "    def _calendar_list_rows(self) -> list[dict[str, object]]:\n",
    task_block,
)
replace_once(
    panel,
    "    def _render_v2_arbeitszentrale(\n"
    "        self,\n"
    "        *,\n"
    "        missed_calls_open: int,\n"
    "        context: OfficePageContext,\n"
    "        kalender_view: str,\n"
    "    ) -> str:\n",
    "    def _render_v2_arbeitszentrale(\n"
    "        self,\n"
    "        *,\n"
    "        missed_calls_open: int,\n"
    "        context: OfficePageContext,\n"
    "        kalender_view: str,\n"
    "        employee_session_token: str | None = None,\n"
    "    ) -> str:\n",
)
replace_once(
    panel,
    "                tasks=self._task_list_rows(),\n",
    "                tasks=self._combined_task_rows(\n"
    "                    context=context,\n"
    "                    employee_session_token=employee_session_token,\n"
    "                ),\n",
)
replace_once(
    panel,
    '        kalender_view: str = "woche",\n    ) -> str:\n',
    '        kalender_view: str = "woche",\n'
    "        employee_session_token: str | None = None,\n"
    "    ) -> str:\n",
)
replace_once(
    panel,
    "                context=context,\n"
    "                kalender_view=kalender_view,\n"
    "            )\n",
    "                context=context,\n"
    "                kalender_view=kalender_view,\n"
    "                employee_session_token=employee_session_token,\n"
    "            )\n",
)

# Dashboard
dashboard = "src/catering_system/ui/office_panel_dashboard.py"
replace_once(
    dashboard,
    '    "payment": "briefcase",\n}',
    '    "payment": "briefcase",\n    "manual": "briefcase",\n}',
)
replace_once(
    dashboard,
    '        href = str(task.get("action_href", ""))\n        rows.append(\n',
    '        href = str(task.get("action_href", ""))\n'
    '        priority = str(task.get("priority_label", ""))\n'
    '        subtitle = str(task.get("subtitle", ""))\n'
    '        meta = " · ".join(part for part in (priority, subtitle) if part)\n'
    "        rows.append(\n",
)
replace_once(
    dashboard,
    '            f"<p>{_e(str(task.get(\'subtitle\', \'\')))}</p></div>"\n',
    '            f"<p>{_e(meta)}</p></div>"\n',
)
replace_once(
    dashboard,
    '            if data.context.can("queue.view")\n',
    '            if data.context.can("tasks.view")\n',
)

# Office HTTP
http = "src/catering_system/ui/office_panel_http.py"
replace_once(
    http,
    "from catering_system.ui.office_panel_authz import (\n",
    "from catering_system.ui.manual_task_presentation import (\n"
    "    parse_subject_reference,\n"
    "    subject_permission,\n"
    ")\n"
    "from catering_system.ui.office_panel_authz import (\n",
)
replace_once(
    http,
    "                        context=context,\n"
    "                        kalender_view=kalender_view,\n"
    "                    )\n",
    "                        context=context,\n"
    "                        kalender_view=kalender_view,\n"
    "                        employee_session_token=self._employee_session_token(),\n"
    "                    )\n",
)
replace_once(
    http,
    '            assigned_to = form.get("assigned_to_employee_id", "").strip()\n'
    "            if assigned_to and not self._require_business_permission_post(\n"
    '                auth, "tasks.assign", active_section="tasks"\n'
    "            ):\n"
    "                return\n"
    "            panel.create_manual_task(\n",
    '            assigned_to = form.get("assigned_to_employee_id", "").strip()\n'
    "            if assigned_to and not self._require_business_permission_post(\n"
    '                auth, "tasks.assign", active_section="tasks"\n'
    "            ):\n"
    "                return\n"
    "            subject_type, _subject_key = parse_subject_reference(\n"
    '                form.get("subject_reference", "")\n'
    "            )\n"
    "            permission = subject_permission(subject_type)\n"
    "            if permission and not self._require_business_permission_post(\n"
    '                auth, permission, active_section="tasks"\n'
    "            ):\n"
    "                return\n"
    "            panel.create_manual_task(\n",
)

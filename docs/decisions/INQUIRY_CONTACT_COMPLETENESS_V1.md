# INQUIRY_CONTACT_COMPLETENESS_V1

Status: implemented (local slice; no production deploy, no migration).

## Business rule

Полноценная клиентская заявка (Inquiry) содержит одновременно **E-Mail** и
**Telefon**. Имя и Firma остаются необязательными.

## Canonical semantics

- Источник истины — структурированный `Inquiry.customer_snapshot`
  (`snapshot_email`, `snapshot_phone`); `intake_message`-метки остаются только
  compatibility-fallback при первоначальном построении snapshot.
- Derived state `InquiryContactCompleteness`
  (`catering_system.domain.inquiry_contact_completeness`):
  `complete | missing_email | missing_phone | missing_email_and_phone`.
- Валидность: e-mail — непустой после trim, содержит `@`, casefold;
  Telefon — непустой результат существующей `normalize_phone`.

## Intake channel rules

- `website_form`, `configurator`: e-mail **и** Telefon обязательны уже при
  создании. Правило enforced в `InquiryService.create_inquiry` (canonical
  service layer) — его нельзя обойти другим entry point с тем же
  `inquiry_source`. Отклонённая заявка не сохраняется частично; website
  idempotency (submission_id) не изменена.
- `email`: допустима preliminary Inquiry с e-mail без Telefon
  (`missing_phone`).
- `phone` / `phone_by_office`: допустима preliminary Inquiry с Telefon без
  e-mail (`missing_email`).
- `manual`: допустима временная неполная Inquiry; Office UI явно показывает,
  какие контакты отсутствуют.

## Structured create contract

`InquiryService.create_inquiry` и `POST /office/v1/inquiries` принимают
optional `contact_email`, `contact_phone`, `contact_name`, `company_name`.
Они строят `InquiryCustomerSnapshot`; клиент не отправляет произвольный
snapshot-JSON. Структурированные значения имеют приоритет над
intake_message-метками.

## Append-only completion

- Существующий непустой e-mail/Telefon **нельзя заменить** (конфликт → 409).
- Отсутствующее поле можно заполнить один раз
  (`complete_inquiry_contact_information`); идентичный повтор idempotent.
- `contact_name`/`company_name` при completion не изменяются.
- Операция использует optimistic concurrency (`expect.updated_at`,
  stale → 409), как existing `update` command.

## Contact completion API

`POST /office/v1/inquiries/{id}/contact-completion`
(args: optional `email`, `phone`; expect: `updated_at`).
Ошибки: 401 unauthorized, 404 not_found, 400 invalid/invalid_contact_value,
409 stale_state, 409 contact_conflict. Контакты не логируются.

Inquiry detail дополнительно возвращает `contact_completeness`,
`missing_contact_fields`, `contact_completion_allowed`
(optional typed fields для RemoteCoreClient; старые consumers не ломаются).

## Gates

Один canonical gate (`inquiry_contact_complete`) подключён к:

- `OfferService.prepare_offer_version` (создание предложения);
- `OfferService.record_sent_evidence` (отправка предложения);
- `OfferService.record_acceptance_evidence` (принятие предложения);
- `OfferService.convert_accepted_offer` — только для **новых** конверсий,
  после conversion-link replay (существующие production Orders не блокируются
  задним числом);
- `OrderService.convert_inquiry_to_order` и `POST .../convert`
  (direct conversion);
- `derive_inquiry_office_state` (`convert`/`convert-accepted` next actions).

Blocker texts (Office): `E-Mail-Adresse fehlt`, `Telefonnummer fehlt`,
`E-Mail-Adresse und Telefonnummer fehlen`; next action:
`Kontaktdaten vervollständigen`.

## Explicitly out of scope

- CustomerIdentity assignment / picker;
- automatic customer matching или creation, phone/fuzzy matching;
- Auerswald/HubSpot linkage;
- изменения `customer_linkage` semantics;
- изменения Order/OrderVersion schema; контакты не копируются в Order;
- migration v5 (колонки snapshot_* существуют с migration v4);
- production deploy/migration/records.

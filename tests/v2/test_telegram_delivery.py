from app.telegram.delivery import MAX_ATTEMPTS, RETRY_DELAYS, make_dedupe_key


def test_delivery_dedupe_key_is_stable_and_scoped():
    first = make_dedupe_key(10, '<b>Hello</b>', 'review_queue', 42)
    assert first == make_dedupe_key(10, '<b>Hello</b>', 'review_queue', 42)
    assert first != make_dedupe_key(11, '<b>Hello</b>', 'review_queue', 42)


def test_enqueue_duplicate_returns_canonical_row(app):
    from app.models import TelegramDelivery, User, UserProfile, db
    from app.telegram.delivery import enqueue_delivery

    with app.app_context():
        user = User(username='dedupe-user', role='student')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=54321))
        first = enqueue_delivery(user.id, 'same', kind='news', dedupe_key='test:dedupe')
        second = enqueue_delivery(user.id, 'same', kind='news', dedupe_key='test:dedupe')
        assert first.delivery_id == second.delivery_id
        assert TelegramDelivery.query.count() == 1


def test_claim_and_recover_processing_delivery(app):
    from datetime import timedelta
    from app.models import TelegramDelivery, User, UserProfile, db, utc_now
    from app.telegram.delivery import claim_due_deliveries, enqueue_delivery, recover_stale_processing

    with app.app_context():
        user = User(username='recovery-user', role='student')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=65432))
        row = enqueue_delivery(user.id, 'recover me', kind='news', dedupe_key='test:recovery')
        claimed = claim_due_deliveries()
        assert row.delivery_id in claimed
        current = db.session.get(TelegramDelivery, row.delivery_id)
        current.processing_started_at = utc_now() - timedelta(minutes=20)
        db.session.commit()
        assert recover_stale_processing(timeout_minutes=10) == 1
        assert db.session.get(TelegramDelivery, row.delivery_id).status == 'retry'


def test_delivery_classifies_retryable_and_permanent_telegram_errors(app, monkeypatch):
    from app.models import TelegramDelivery, User, UserProfile, db
    from app.telegram.delivery import claim_due_deliveries, deliver_one, enqueue_delivery

    with app.app_context():
        user = User(username='error-user', role='student')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=76543))
        row = enqueue_delivery(user.id, 'temporary', kind='news', dedupe_key='test:temporary')
        monkeypatch.setattr('app.telegram.delivery.send_telegram_message', lambda *_args, **_kwargs: {'ok': False, 'error_code': 500, 'description': 'temporary'})
        claim_due_deliveries()
        assert deliver_one(row.delivery_id)['status'] == 'retry'

        row2 = enqueue_delivery(user.id, 'permanent', kind='news', dedupe_key='test:permanent')
        monkeypatch.setattr('app.telegram.delivery.send_telegram_message', lambda *_args, **_kwargs: {'ok': False, 'error_code': 400, 'description': 'blocked'})
        claim_due_deliveries()
        assert deliver_one(row2.delivery_id)['status'] == 'failed'
        assert db.session.get(TelegramDelivery, row2.delivery_id).last_error == 'blocked'


def test_outbox_enqueue_failure_rolls_back_notification(app, monkeypatch):
    from app.models import User, UserNotification, UserProfile, db
    from app.notifications.service import notify_user

    with app.app_context():
        user = User(username='rollback-user', role='student')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=87654))
        monkeypatch.setattr('app.telegram.delivery.enqueue_delivery', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('outbox unavailable')))
        try:
            notify_user(user.id, kind='news', title='must rollback')
        except RuntimeError:
            db.session.rollback()
        assert UserNotification.query.filter_by(user_id=user.id).count() == 0


def test_delivery_retry_policy_is_bounded():
    assert MAX_ATTEMPTS == 5
    assert RETRY_DELAYS == (60, 300, 900, 3600, 21600)


def test_notification_and_delivery_are_created_in_same_transaction(app):
    from app.models import User, UserProfile, UserNotification, TelegramDelivery, db
    from app.notifications.service import notify_user

    with app.app_context():
        user = User(username='outbox-user', role='student')
        db.session.add(user)
        db.session.flush()
        db.session.add(UserProfile(user_id=user.id, telegram_chat_id=12345))
        notify_user(user.id, kind='review_queue', title='Проверка', body='Есть работа')
        db.session.commit()
        assert UserNotification.query.count() == 1
        delivery = TelegramDelivery.query.one()
        assert delivery.notification_id == UserNotification.query.one().notification_id
        assert delivery.status == 'pending'

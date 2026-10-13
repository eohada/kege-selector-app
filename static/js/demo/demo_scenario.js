/**
 * BooStudy Demo Scenario
 * Declarative chapter structure, branching choices, and character dialogs.
 * UI Canon compliant: Zero emojis, semantic messaging, modular architecture.
 */
(function (global) {
  'use strict';

  var SCENARIO = {
    version: 1,

    // Реакции на выход за рамки сценария
    outOfBounds: {
      blockedArea: {
        emotion: 'gentle_warning',
        message: 'Эй, туда нам пока рановато! Этот раздел станет доступен после регистрации. Давай вернёмся к нашей миссии!',
        buttonText: 'Вернуться в кабинет',
      },
      genericHint: {
        emotion: 'curious',
        message: 'Ты можешь свободно исследовать доступные разделы, а когда будешь готов — возвращайся ко мне!',
      },
    },

    chapters: {
      chapter_1: {
        id: 'chapter_1',
        title: 'Глава 1. Знакомство',
        steps: {
          welcome: {
            id: 'welcome',
            emotion: 'happy',
            characterTag: 'Проводник Бу',
            message: 'Привет! Я Бу — твой персональный цифровой проводник в BooStudy. Я помогу тебе освоиться на платформе и подготовиться к максимуму на экзамене!',
            nextStep: 'name_input',
            buttons: [
              { label: 'Привет, Бу! Начнём', action: 'next' },
            ],
          },
          name_input: {
            id: 'name_input',
            emotion: 'curious',
            characterTag: 'Проводник Бу',
            message: 'Как тебя зовут? Напиши своё имя, чтобы мы могли общаться по-человечески.',
            nextStep: 'goal_selection',
          },
          goal_selection: {
            id: 'goal_selection',
            emotion: 'thinking',
            characterTag: 'Проводник Бу',
            templateMessage: 'Приятно познакомиться, {name}! Скажи, к чему ты планируешь готовиться?',
            fallbackMessage: 'Приятно познакомиться! Скажи, к чему ты планируешь готовиться?',
            choices: [
              { id: 'ege_100', label: 'ЕГЭ по информатике на 90+', flag: 'goal_ege_high', nextStep: 'finish_ch1' },
              { id: 'oge_prep', label: 'ОГЭ на пятёрку', flag: 'goal_oge', nextStep: 'finish_ch1' },
              { id: 'programming', label: 'Изучить программирование', flag: 'goal_programming', nextStep: 'finish_ch1' },
              { id: 'explore', label: 'Просто смотрю платформу', flag: 'goal_explore', nextStep: 'finish_ch1' },
            ],
          },
          finish_ch1: {
            id: 'finish_ch1',
            emotion: 'celebrating',
            characterTag: 'Проводник Бу',
            templateMessage: 'Отличный выбор, {name}! Сейчас покажу не обещание, а пример твоего кабинета спустя полгода регулярной работы. Это демонстрационный маршрут по информатике — пройдём его вместе, шаг за шагом.',
            fallbackMessage: 'Отличный выбор! Сейчас покажу пример кабинета спустя полгода регулярной работы — это демонстрационный маршрут по информатике. Пойдём шаг за шагом.',
            nextChapter: 'chapter_2',
            nextStep: 'dashboard_intro',
            buttons: [
              { label: 'Перейти в кабинет', action: 'goto_dashboard' },
            ],
          },
        },
      },

      chapter_2: {
        id: 'chapter_2',
        title: 'Глава 2. Учебная база',
        hudTitle: 'Глава 2/3 · Учебная база',
        steps: {
          dashboard_intro: {
            id: 'dashboard_intro',
            emotion: 'happy',
            characterTag: 'Учебный дашборд',
            templateMessage: '{name}, добро пожаловать в свою учебную базу! Я уже кое-что для тебя подготовил. Здесь будут занятия, задания, результаты и всё, что поможет двигаться к цели. Давай вместе посмотрим, как всё устроено!',
            fallbackMessage: 'Добро пожаловать в свою учебную базу! Здесь будут занятия, задания, результаты и всё, что поможет двигаться к цели.',
            buttons: [
              { label: 'Показывай!', action: 'start_chapter2_mission' },
            ],
            nextStep: 'chapter2_mission',
          },
          chapter2_mission: {
            id: 'chapter2_mission',
            emotion: 'curious',
            characterTag: 'Наш следующий шаг',
            message: 'Пойдём по порядку: сначала я покажу программу обучения, потом комнату уже прошедшего урока и отдельное задание. После каждого экрана вернёмся сюда — тебе не придётся гадать, куда идти.',
            target: 'learning-program',
          },
          chapter2_discovery: {
            id: 'chapter2_discovery',
            emotion: 'celebrating',
            characterTag: 'Первое испытание',
            message: 'Маршрут осмотрен. Следующий кадр — первое испытание: там можно выбрать ручную трассировку алгоритма или короткую задачу с кодом.',
            target: 'recent-assignments',
            buttons: [
              { label: 'Посмотреть задание', action: 'goto_trial' },
            ],
          },
          explore_cards: {
            id: 'explore_cards',
            emotion: 'curious',
            characterTag: 'Следующий кадр',
            message: 'Все нужные части кабинета уже показаны. Продолжаем по маршруту к первому испытанию.',
            target: 'recent-assignments',
            buttons: [
              { label: 'К испытанию', action: 'goto_trial' },
            ],
            nextStep: 'ready_for_trial',
          },
          ready_for_trial: {
            id: 'ready_for_trial',
            emotion: 'celebrating',
            characterTag: 'Первый вызов',
            message: 'Ты быстро ориентируешься! А теперь самое интересное: я приготовил для тебя боевое демонстрационное задание в Task Workspace. Проверим силы?',
            nextChapter: 'chapter_3',
            nextStep: 'trial_intro',
            buttons: [
              { label: 'Перейти к испытанию', action: 'goto_trial' },
            ],
          },
        },
      },

      chapter_3: {
        id: 'chapter_3',
        title: 'Глава 3. Первое испытание',
        hudTitle: 'Глава 3/3 · Первое испытание',
        steps: {
          trial_intro: {
            id: 'trial_intro',
            emotion: 'curious',
            characterTag: 'Испытание',
            message: 'Перед тобой первое демонстрационное задание по программированию. Выбери режим: вручную проследить короткий алгоритм или написать небольшой цикл с понятным результатом.',
            target: 'task-card',
            buttons: [
              { label: 'Я готов решать!', action: 'focus_input' },
            ],
            nextStep: 'trial_input',
          },
          trial_input: {
            id: 'trial_input',
            emotion: 'thinking',
            characterTag: 'Решение задачи',
            message: 'Введи ответ в поле ниже и нажми «Отправить ответ». Я моментально проверю твой результат!',
            target: 'task-input',
            buttons: [
              { label: 'Подсказать', action: 'show_hint' },
            ],
          },
          trial_retry: {
            id: 'trial_retry',
            emotion: 'thinking',
            characterTag: 'Ещё одна попытка',
            message: 'Первый ход не сошёлся — это нормально. Выбери: вернуться к ответу с новой подсказкой или сначала разобрать принцип в библиотеке.',
            buttons: [
              { label: 'Попробовать ещё раз', action: 'retry_trial' },
              { label: 'Сначала понять принцип', action: 'branch_to_library', secondary: true },
            ],
          },
          victory: {
            id: 'victory',
            emotion: 'celebrating',
            characterTag: 'Первое испытание пройдено',
            templateMessage: 'Блестяще, {name}! Первое испытание пройдено на максимум (1 из 1 балла)! Ты почувствовал, как удобно сдавать задания в BooStudy. Прогресс зафиксирован.',
            fallbackMessage: 'Блестяще! Первое испытание пройдено на максимум (1 из 1 балла)! Ты почувствовал, как удобно сдавать задания в BooStudy. Прогресс зафиксирован.',
            buttons: [
              { label: 'Открыть секретную библиотеку', action: 'start_library' },
              { label: 'Смотреть решение', action: 'view_solution' },
              { label: 'Вернуться в кабинет', action: 'goto_dashboard', secondary: true },
            ],
          },
        },
      },

      chapter_4: {
        id: 'chapter_4', title: 'Глава 4. Секретная библиотека',
        steps: { library_intro: { id: 'library_intro', emotion: 'curious', characterTag: 'Секретная библиотека', message: 'Теперь разберёмся, почему решение сработало. В библиотеке собраны материалы, которые помогают понимать принцип, а не просто запоминать ответ.', buttons: [{ label: 'Открыть теорию', action: 'goto_theory' }] }, library_opened: { id: 'library_opened', emotion: 'happy', characterTag: 'Секретная библиотека', message: 'Ты в библиотеке. Выбери материал и посмотри, как объяснение превращает сложную задачу в понятный принцип.', buttons: [{ label: 'К работе над ошибками', action: 'start_mistakes' }] } },
      },
      chapter_5: {
        id: 'chapter_5', title: 'Глава 5. Ошибаться — нормально',
        steps: { mistakes_intro: { id: 'mistakes_intro', emotion: 'thinking', characterTag: 'Работа над ошибками', message: 'Ошибки — это подсказки к следующему шагу. Посмотри проверенную работу и комментарий наставника: так можно превратить трудную тему в освоенный навык.', buttons: [{ label: 'Открыть мои работы', action: 'goto_assignments' }] }, mistakes_opened: { id: 'mistakes_opened', emotion: 'happy', characterTag: 'Работа над ошибками', message: 'Здесь хранятся твои решения и обратная связь. Исправление — это не шаг назад, а самый короткий путь к уверенному ответу.', buttons: [{ label: 'Исправить ответ', action: 'goto_mistake_retry' }, { label: 'Посмотреть свой маршрут', action: 'start_route', secondary: true }] } },
      },
      chapter_6: {
        id: 'chapter_6', title: 'Глава 6. Твой маршрут',
        steps: { route_intro: { id: 'route_intro', emotion: 'happy', characterTag: 'Твой маршрут', message: 'У каждого ученика свой темп. В индивидуальной программе видно, что уже освоено, что сейчас в фокусе и что ждёт дальше.', buttons: [{ label: 'Открыть программу', action: 'goto_program' }] }, route_opened: { id: 'route_opened', emotion: 'curious', characterTag: 'Твой маршрут', message: 'Отмечай пройденное и возвращайся к текущей теме в своём темпе. Такой маршрут помогает видеть не только цель, но и ближайший шаг.', buttons: [{ label: 'Посмотреть маленькие победы', action: 'start_wins' }] } },
      },
      chapter_7: {
        id: 'chapter_7', title: 'Глава 7. Маленькие победы',
        steps: { wins_intro: { id: 'wins_intro', emotion: 'celebrating', characterTag: 'Маленькие победы', message: 'Каждый решённый шаг складывается в прогресс. Давай посмотрим, как твои уроки и работы превращаются в результат.', buttons: [{ label: 'Открыть аналитику', action: 'goto_analytics' }] }, wins_opened: { id: 'wins_opened', emotion: 'celebrating', characterTag: 'Маленькие победы', message: 'Твой результат складывается из небольших, но честных побед. Ты уже умеешь ориентироваться в своей учебной базе.', buttons: [{ label: 'Завершить приключение', action: 'goto_finale' }] } },
      },
      chapter_8: {
        id: 'chapter_8', title: 'Глава 8. Ритм занятий',
        steps: {
          schedule_intro: { id: 'schedule_intro', emotion: 'happy', characterTag: 'Твой ритм', message: 'Теперь заглянем в расписание. В демо это пример удобного учебного ритма на текущую неделю — настоящее расписание мы не меняем.', buttons: [{ label: 'Открыть расписание', action: 'open_schedule' }] },
          schedule_opened: { id: 'schedule_opened', emotion: 'curious', characterTag: 'Твой ритм', message: 'Два занятия вечером и короткая самостоятельная практика между ними — так регулярность не превращается в гонку. Следом покажу профиль и достижения.', buttons: [{ label: 'Посмотреть профиль', action: 'open_profile' }] }
        },
      },
      chapter_9: {
        id: 'chapter_9', title: 'Глава 9. Профиль ученика',
        steps: {
          profile_intro: { id: 'profile_intro', emotion: 'celebrating', characterTag: 'Твои достижения', message: 'В профиле собраны не только цифры, но и маленькие поводы собой гордиться. Посмотри на уровень, серию занятий и достижения.', buttons: [{ label: 'Открыть достижения', action: 'open_profile' }] },
          profile_opened: { id: 'profile_opened', emotion: 'celebrating', characterTag: 'Твои достижения', message: 'Вот как может выглядеть профиль после полугода регулярной работы. Остался последний кадр — выберем первый шаг уже для тебя.', buttons: [{ label: 'К финалу', action: 'goto_finale' }] }
        },
      },
      chapter_10: {
        id: 'chapter_10', title: 'Финал',
        steps: { finale: { id: 'finale', emotion: 'celebrating', characterTag: 'Твой следующий шаг', templateMessage: '{name}, теперь ты видел не обещание, а путь: цель, практика, поддержка и рост. Выбери, с какого первого шага начнём.', buttons: [] } },
      },
    },
  };

  global.BooDemoScenario = SCENARIO;

})(typeof window !== 'undefined' ? window : this);

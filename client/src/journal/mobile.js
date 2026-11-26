const reader = new TodayJournal(document.getElementById('root'), action => {
  window.TebbJournal.perform(JSON.stringify(action));
}, 'mobile');
window.updateJournal = state => reader.update(state);

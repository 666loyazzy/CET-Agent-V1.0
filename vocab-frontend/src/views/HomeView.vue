<script setup lang="ts">
import { DictionaryService } from '@/api/api';
import {
  fetchList as apiFetchList,
  submitReview as apiSubmitReview,
  fetchToday as apiFetchToday,
  submitListReview as apiSubmitListReview,
  setReviewFlag as apiSetReviewFlag,
} from '@/api/vocab';
import lettersAudio from '@/utils/letter';
import allWords from '@/utils/words';
import { onMounted, onUnmounted, reactive, computed, watch, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRouter, useRoute } from 'vue-router';
// import { ElLoading } from 'element-plus'
import { isLetter } from '@/utils/keyborad';
import Message from '@/components/IMessage.vue'
import HelpModal from '@/components/HelpModal.vue'
import TopNav from '@/components/TopNav.vue'

import audioManager from '@/utils/audio';


const router = useRouter();
const route = useRoute();

const skillInputRef = ref<any>(null);
const showHelpModal = ref(false);

const handleSkillEnter=()=>{
  state.skillFocus = false
  skillInputRef.value.blur()
}

const type: any = route.query.type || 'etc4';
const review: any = route.query.review || '0';
const initialListNo: number = Math.max(1, Number(route.query.list) || 1);
const initialBook: 'cet4' | 'cet6' =
  localStorage.getItem('cet-agent-level') === 'CET-6' ? 'cet6' : 'cet4';

function shuffled<T>(arr: T[] | undefined | null): T[] {
  if (!arr || !arr.length) return []
  const out = arr.slice()
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

const state: any = reactive({
  type,
  list: shuffled(allWords[type] || allWords.etc4),
  reviewType: review,
  current: 0,
  audioIndex: 0,
  explainStatus: '',
  enterAudio: 'mean_en',//'sentence'
  reviewSentence: false, // 复习状态展示词根和例句
  msg:{
    type:'error',
    text: ''
  },
  explain: {
    abandoned:{
      mean_en: 'forsaken by owner or keeper; free from constraint.',
      mean_cn: 'adj. 被抛弃的；废弃的，放纵的，不再考虑的; v. 放弃，逃离，中止（abandon 的过去式和过去分词）',
      word_etyma: '',
      sentence: `At the captain's order, they abandoned ship.`,
      sentence_trans: '在船长的命令下，他们弃船离开了。'
    },
    Christ: {
      mean_cn: '基督; 耶稣基督'
    },
    ninetheen:{
      mean_cn: '十九'
    },
  },
  currentSkillWord: '',
  skills: {},
  skillFocus: false,
  // Local-API state — populated when using CET-4 list; fallback keeps hardcoded etc4 usable.
  wordIdByEn: {} as Record<string, number>,
  wordHadError: false,
  listNo: initialListNo,
  book: initialBook,
  // Tracks whether the current word has been flagged mastered in this session.
  // Cleared on word change via the watch(currentWord) below.
  markedCurrent: false,
})

async function markCurrentMastered() {
  const en = (currentWord.value || '').toLowerCase()
  const wid = state.wordIdByEn[en]
  if (!wid || state.markedCurrent) return
  try {
    await apiSetReviewFlag({ word_id: wid, flag: 2 })
    state.markedCurrent = true
  } catch (e) {
    console.warn('[vocab] markCurrentMastered failed:', e)
  }
}

function onLevelChange(lv: 'CET-4' | 'CET-6') {
  const nextBook: 'cet4' | 'cet6' = lv === 'CET-6' ? 'cet6' : 'cet4'
  if (nextBook === state.book) return
  // Reset to list 1 on level change — user's mental model is "switch book,
  // start fresh". listNo is per-book anyway.
  state.listNo = 1
  loadCetList(nextBook, 1)
}

async function loadCetList(book: 'cet4' | 'cet6', listNo: number) {
  try {
    const words = await apiFetchList(book, listNo)
    state.wordIdByEn = Object.fromEntries(words.map(w => [w.en.toLowerCase(), w.id]))
    state.list = shuffled(words.map(w => w.en))
    state.current = 0
    state.book = book
    state.listNo = listNo
  } catch (e) {
    console.warn('[vocab] fetchList failed, using bundled fallback:', e)
    state.wordIdByEn = {}
    state.list = shuffled(allWords.etc4)
  }
}

function fireReview(wordEn: string) {
  const wid = state.wordIdByEn[(wordEn || '').toLowerCase()]
  if (!wid) return
  apiSubmitReview(wid, !state.wordHadError).catch((e) => {
    console.warn('[vocab] submitReview failed:', e)
  })
}

async function finalizeCurrentList() {
  if (!Object.keys(state.wordIdByEn).length) return
  try {
    const r = await apiSubmitListReview(state.book, state.listNo)
    const pct = Math.round(r.session_rate * 100)
    const msg = r.remembered
      ? `本轮记忆率 ${pct}%，进入阶段 ${r.ebbinghaus_stage}，下次复习 ${r.days_until_due} 天后 (${r.next_due_date})`
      : `本轮记忆率 ${pct}%，未达到 70%，明天再来一遍`
    // Default (confirm) = the action that makes sense for the outcome.
    // Cancel = the other reasonable choice. Either way we end up in a
    // usable state — no blank playground.
    const primaryIsNext = r.remembered
    ElMessageBox.confirm(msg, `List ${state.listNo} 完成`, {
      confirmButtonText: primaryIsNext ? '下一个 list' : '再来一遍',
      cancelButtonText: primaryIsNext ? '重刷本 list' : '跳过到下个',
      type: r.remembered ? 'success' : 'warning',
      closeOnClickModal: false,
      closeOnPressEscape: false,
    })
      .then(async () => {
        if (primaryIsNext) await jumpToNextDue()
        else await loadCetList(state.book, state.listNo)
      })
      .catch(async () => {
        if (primaryIsNext) await loadCetList(state.book, state.listNo)
        else await jumpToNextDue()
      })
  } catch (e) {
    console.warn('[vocab] finalizeList failed:', e)
    ElMessage.warning('保存 list 进度失败：' + e)
  }
}

async function jumpToNextDue() {
  try {
    const today = await apiFetchToday(state.book)
    const next = today.lists.find(l => l.list_no !== state.listNo) ?? today.lists[0]
    if (next) {
      await loadCetList(state.book, next.list_no)
      router.replace({ query: { ...route.query, list: String(next.list_no) } })
    } else {
      ElMessage.success('今日复习全部完成 🎉')
    }
  } catch (e) {
    console.warn('[vocab] jumpToNextDue failed:', e)
  }
}

const currentWord = computed(()=>{
  return route.query.word || state.list?.[state.current]?.split(' ')[0] || ''
})

const nextWord = computed(()=>{
  return state.list?.[state.current+1]?.split(' ')[0] || ''
})

const currentSkill = computed({
        get() {
          console.log('get-value', state.skills, currentWord.value, state.current)
          return state.skills?.[currentWord.value]
        },
        set(value) {
          console.log('set-value', state.skills, currentWord.value, state.current)
          if(!state.skills){
            state.skills = {};
          }
          state.skills[currentWord.value] = value;
        }
      })

const showErrorMessage=(text = '')=>{
  state.msg.text = text;
  setTimeout(()=>state.msg.text = '', 2000);
}

const currentExplain = computed(()=>{
  return state.explain[currentWord.value]
})

const handleClickSentence=(sentence: string)=>{
  audioManager.playOnlineAudio(sentence);
}

const onSkillChange=(val:string)=>{
  console.log('currentSkill',currentSkill, state.skills)
  localStorage.setItem('word_skills', JSON.stringify({...state.skills,[currentWord.value]:val}))
}

const switchWordList = (newType: string) => {
  state.type = newType;
  state.current = 0;
  localStorage.setItem('current_index', '0');
  
  if (newType === 'etc4') {
    loadCetList(state.book, state.listNo || 1);
  } else if (newType === 'all') {
    const wordsJson = localStorage.getItem('word_list');
    if (wordsJson) {
      const data = JSON.parse(wordsJson);
      state.list = shuffled(data.list);
    } else {
      DictionaryService.getWordList().then(({data}:any)=>{
        state.list = shuffled(data.list);
        localStorage.setItem('word_list', JSON.stringify(data))
      })
    }
  } else if (newType === 'custom') {
    // 自定义单词列表，这里可以添加相关逻辑
    const wordsJson = localStorage.getItem('custom_word_list');
    if (wordsJson) {
      const data = JSON.parse(wordsJson);
      state.list = shuffled(data.list || []);
    } else {
      // 如果没有自定义列表，则初始化为空数组
      state.list = [];
    }
  }
  
  // 更新路由但不刷新页面
  router.replace({ query: { ...route.query, type: newType } });
}

const handleKeyPress = (event:any) => {
  if(state.skillFocus || event.altKey || event.ctrlKey || event.metaKey){
    return;
  }
  if(['ArrowRight','Enter'].includes(event.key)){
    const isLastInList = state.current >= state.list.length - 1;
    fireReview(currentWord.value);
    state.wordHadError = false;
    if (isLastInList && Object.keys(state.wordIdByEn).length) {
      finalizeCurrentList();
      return;
    }
    state.current++;
    state.audioIndex = 0;
    state.enterAudio = 'mean_en';
    state.reviewSentence = false;
    localStorage.setItem('current_index', state.current);
    resetRouter();
  }else if(['ArrowLeft'].includes(event.key)){
    if(state.current>0){
      state.current--;
      state.audioIndex = 0;
      state.enterAudio = 'mean_en';
      state.reviewSentence = false;
      state.wordHadError = false;
      localStorage.setItem('current_index', state.current);
    }else{
      showErrorMessage('已经是第一个了');
    }
  }else if(['ArrowUp', 'ArrowDown', 'Tab', 'Shift'].includes(event.key)){
    event.preventDefault?.();
    if(state.reviewType!=='0' && !state.reviewSentence){
      state.reviewSentence = true;
      return;
    }
    if(currentExplain.value?.[state.enterAudio]){
      // audio = new Audio(`https://dict.youdao.com/dictvoice?type=0&audio=${currentExplain.value[state.enterAudio]}`);
      audioManager.playOnlineAudio(currentExplain.value[state.enterAudio]);
      state.enterAudio = state.enterAudio === 'mean_en'?'sentence':'mean_en';
    }else if(currentExplain.value){
      state.enterAudio = state.enterAudio === 'mean_en'?'sentence':'mean_en';
    }
  }else if (event.key === ' ') {
    // audio = new Audio(`https://dict.youdao.com/dictvoice?type=0&audio=${currentWord.value}`);
    audioManager.playOnlineAudio(currentWord.value);
    // console.log('message==>', state.audioIndex)
    // if(state.audioIndex > (currentWord.value.length-1)*2){
    //   state.audioIndex = 0
    // }
    // audioManager.playLetter(event.key.toLowerCase());
  }else if(currentWord.value[state.audioIndex % (currentWord.value.length)]===event.key){
    const config = lettersAudio[event.key.toLowerCase()];
    if(!config?.url){
      showErrorMessage('程序遇到Bug，请联系QQ: 907203644')
    }
    // audio = new Audio(location.origin+location.pathname+config.url);
    // audio.playbackRate = 2; // 播放速度为0.5 - 2倍
    // Object.keys(config).forEach(key=>{
    //   if(key!=='url'){
    //     audio[key] = config[key];
    //   }
    // });
    audioManager.playLetter(event.key.toLowerCase());
    if(state.audioIndex > (currentWord.value.length-1)*2){
      state.audioIndex = 0
    }else{
      state.audioIndex++;
    }
  }else if(isLetter(event)){
    const errorChar = currentWord.value[state.audioIndex % currentWord.value.length];
    if(errorChar){
      showErrorMessage('请输入：' + currentWord.value[state.audioIndex % currentWord.value.length])
    }
    state.wordHadError = true;
    audioManager.playErrorSound();
  }
  // if(audio){
  //   audio.play();
  // }
};

const resetRouter=()=>router.push({ query: state.reviewType !== '0'?{review:state.reviewType}:{} });

const getWordExplain=(newWord: string)=>{
  state.explainStatus = 'loading';
  // const loadingInstance = ElLoading.service({
  //   target: '.explain_status',
  //   text: '这个单词几个意思...',
  //   fullscreen: false
  // })
  DictionaryService.getWordMean(newWord).then(({data}:any)=>{
    state.explain[newWord] = data;
    localStorage.setItem(newWord, JSON.stringify(data))
    state.explainStatus = '';
  }).catch(()=>{
    state.explainStatus = 'error';
  }).finally(()=>{
    //loadingInstance.close()
  })
}

watch(()=>state.reviewType,(newType)=>{
  if(newType !=='0'){
    state.audioIndex = state.reviewType * currentWord.value.length;
  }else{
    state.audioIndex = 0
    resetRouter();
  }
})

watch(()=>state.current, (val:number)=>{
  localStorage.setItem('current_index','' + val);
  localStorage.setItem('max_index', '' + Math.max(val, +(localStorage.getItem('max_index') || 0)));
})

watch(currentWord, (newWord: string)=>{
  state.markedCurrent = false;
  if(!newWord) return;
  state.audioIndex = state.reviewType * newWord.length;
  audioManager.preloadAllOnlineAudios([newWord, state.explain[currentWord.value]?.mean_en, state.explain[currentWord.value]?.sentence].filter(Boolean));
  if(state.explain[newWord]){
    return;
  }
  const wordJson = localStorage.getItem(newWord);
  if(wordJson){
    state.explain[newWord] = JSON.parse(wordJson);
    return;
  }
  getWordExplain(newWord);
}, { immediate: true })

watch(nextWord, (newWord: string)=>{
  if(!newWord) return;
  if(state.explain[newWord]){
    return;
  }
  const wordJson = localStorage.getItem(newWord);
  if(wordJson){
    state.explain[newWord] = JSON.parse(wordJson);
    return;
  }
  getWordExplain(newWord);
}, { immediate: true })

watch(()=>route.query, (val)=>{
  if(Object.keys(val).length>0){
    location.reload()
  }
})


onMounted(() => {
  audioManager.preloadAllLetters()
  window.addEventListener('keydown', handleKeyPress);
  state.current = route.query.index||localStorage.getItem('current_index') || 0;
  const wordSkills = localStorage.getItem('word_skills');
  if(wordSkills){
    state.skills = JSON.parse(wordSkills);
    console.log('---', state.skills);
  }
  
  // 检查是否需要显示帮助弹窗
  const helpModalClosed = localStorage.getItem('helpModalClosed');
  if (!helpModalClosed) {
    showHelpModal.value = true;
  }
  
  if(type==='etc4'){
    // Prefer today's due list if user didn't explicitly request one via ?list.
    if (!route.query.list) {
      apiFetchToday(state.book).then((today) => {
        const next = today.lists[0];
        if (next) {
          loadCetList(state.book, next.list_no);
        } else {
          loadCetList(state.book, initialListNo);
        }
      }).catch(() => loadCetList(state.book, initialListNo));
    } else {
      loadCetList(state.book, initialListNo);
    }
    return;
  }
  if(type==='all'){
      const wordsJson = localStorage.getItem('word_list');
      if(wordsJson){
        const data = JSON.parse(wordsJson);
        state.list = shuffled(data.list);
        return;
      }

      DictionaryService.getWordList().then(({data}:any)=>{
        state.list = shuffled(data.list);
        localStorage.setItem('word_list', JSON.stringify(data))
      })
  }else if(type === 'custom'){
    const wordsJson = localStorage.getItem('word_list');
    if(wordsJson){
      const data = JSON.parse(wordsJson);
      state.list = shuffled(data.list);
    }
  }
});


onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyPress);
});

</script>

<template>
  <TopNav active="typing" @level-change="onLevelChange" />
  <main>
    <div class="header">
      <span class="header-left">
        <el-select class="type-select" v-model="state.type" @change="switchWordList" size="small" style="background: #333; width: 120px; margin-right: 10px;">
          <el-option label="CET 词汇" value="etc4"></el-option>
          <el-option label="10000+" value="all"></el-option>
          <el-option label="自定义词汇" value="custom"></el-option>
        </el-select>
        <el-link :underline="false" href="https://lixunchang.github.io/cet4-word-game/#/search" target="_blank">模糊搜索</el-link>
      </span>
      <span class="header-right">
        <span class="steps">
          <span v-if="state.type==='etc4'">{{state.book === 'cet6' ? 'CET-6' : 'CET-4'}} L{{state.listNo}} · </span>{{state.current}} / {{state.list.length}}
        </span>
        <el-switch
          v-model="state.reviewType"
          class="review-type"
          inline-prompt
          active-text="复习"
          inactive-text="陪练"
          active-value="1"
          inactive-value="0"
        />
        <el-button class="help-button" @click="showHelpModal = true">使用帮助</el-button>
      </span>
    </div>
    <message v-show="state.msg.text" :text="state.msg.text" :type="state.msg.type"/>
    <div class="playground" :data-word="currentWord">
      <span class="char" v-for="(char,index) in currentWord" :key="currentWord+'-'+index" :class="{
        'audio_char': state.audioIndex < currentWord.length && state.audioIndex > index,
        'equal_char': state.audioIndex!==0 && state.audioIndex % (currentWord.length) === 0,
        'reserve_char': state.audioIndex >= currentWord.length && state.audioIndex % (currentWord.length+1) < index
      }">
        {{char}}
      </span>
      <div class="skill">
        <el-input
          ref="skillInputRef"
          v-model="currentSkill" 
          :placeholder="state.skillFocus?'记录下自己的速记方法，60个字内...':''" 
          maxlength="60" 
          :show-word-limit2="state.skillFocus" 
          @focus="state.skillFocus = true" 
          @blur="state.skillFocus = false" 
          @keyup.enter="handleSkillEnter"
          @change="onSkillChange"
        >
          <!-- <template v-if="state.skillFocus" #prepend>备注：</template> -->
        </el-input>
      </div>
    </div>
    <div class="explain_status">
      <div class="explain" v-if="currentExplain">
        <p v-if="currentExplain.mean_en" style="color:#999;cursor:pointer;" @click="handleClickSentence(currentExplain.mean_en)">
          <label>英文</label>
          <span style="flex:1;" class="ellipsis_word">{{currentExplain.mean_en}}</span>
        </p>
        <p v-if="currentExplain.mean_cn" class="chinese">
          <label>中文</label>
          <span style="flex:1;text-align:left;color:red;font-weight: bold;">
            <span style="flex:1;">{{currentExplain.mean_cn}}</span>
          </span>
        </p>
        <p v-if="currentExplain.word_etyma&&(state.reviewType==='0'||state.reviewSentence)">
          <label>词根</label>
          <span style="flex:1;color:#555;">{{currentExplain.word_etyma}}</span>
        </p>
        <p v-if="currentExplain.sentence&&(state.reviewType==='0'||state.reviewSentence)" @click="handleClickSentence(currentExplain.sentence)" style="cursor: pointer;">
          <label>例句</label>
          <span style="flex:1;color:#666;">{{currentExplain.sentence}}</span>
        </p>
        <p v-if="currentExplain.sentence_trans&&(state.reviewType==='0'||state.reviewSentence)">
          <label>翻译</label>
          <span style="flex:1;text-align:left;color:#b2b2b2;">{{currentExplain.sentence_trans}}</span>
        </p>
        <div v-if="state.type==='etc4' && state.wordIdByEn[currentWord?.toLowerCase()]" class="mark-actions">
          <button class="mark-btn" @click="markCurrentMastered" :disabled="state.markedCurrent">
            {{ state.markedCurrent ? '✓ 已标记' : '标记为已掌握' }}
          </button>
          <span class="mark-hint">已掌握的词下次不再出现在这个 list</span>
        </div>
      </div>
      <div v-else-if="state.explainStatus" class="explain_result">
        <span v-if="state.explainStatus === 'loading'" style="color:#999;">努力查询中...</span>
        <span style="cursor:pointer;" v-if="state.explainStatus === 'error'" @click="getWordExplain(currentWord)">查询失败，请刷新重试</span>
      </div>
    </div>
    <div class="key-board">
      <div class="letters">
        <div>
          <span @click="handleKeyPress({key:'q', keyCode: 66})">Q</span>
          <span @click="handleKeyPress({key:'w', keyCode: 66})">W</span>
          <span @click="handleKeyPress({key:'e', keyCode: 66})">E</span>
          <span @click="handleKeyPress({key:'r', keyCode: 66})">R</span>
          <span @click="handleKeyPress({key:'t', keyCode: 66})">T</span>
          <span @click="handleKeyPress({key:'y', keyCode: 66})">Y</span>
          <span @click="handleKeyPress({key:'u', keyCode: 66})">U</span>
          <span @click="handleKeyPress({key:'i', keyCode: 66})">I</span>
          <span @click="handleKeyPress({key:'o', keyCode: 66})">O</span>
          <span @click="handleKeyPress({key:'p', keyCode: 66})">P</span>
        </div>
        <div>
          <span @click="handleKeyPress({key:'a', keyCode: 66})">A</span>
          <span @click="handleKeyPress({key:'s', keyCode: 66})">S</span>
          <span @click="handleKeyPress({key:'d', keyCode: 66})">D</span>
          <span @click="handleKeyPress({key:'f', keyCode: 66})">F</span>
          <span @click="handleKeyPress({key:'g', keyCode: 66})">G</span>
          <span @click="handleKeyPress({key:'h', keyCode: 66})">H</span>
          <span @click="handleKeyPress({key:'j', keyCode: 66})">J</span>
          <span @click="handleKeyPress({key:'k', keyCode: 66})">K</span>
          <span @click="handleKeyPress({key:'l', keyCode: 66})">L</span>
        </div>
        <div>
          <span @click="handleKeyPress({key:'z', keyCode: 66})">Z</span>
          <span @click="handleKeyPress({key:'x', keyCode: 66})">X</span>
          <span @click="handleKeyPress({key:'c', keyCode: 66})">C</span>
          <span @click="handleKeyPress({key:'v', keyCode: 66})">V</span>
          <span @click="handleKeyPress({key:'b', keyCode: 66})">B</span>
          <span @click="handleKeyPress({key:'n', keyCode: 66})">N</span>
          <span @click="handleKeyPress({key:'m', keyCode: 66})">M</span>
        </div>
      </div>
      <div class="action">
        <span @click="handleKeyPress({key:'ArrowRight'})">下一个</span>
        <span style="flex:2;" @click="handleKeyPress({key:' '})">空格</span>
        <span @click="handleKeyPress({key:'ArrowLeft'})">上一个</span>
      </div>
    </div>
  </main>
  <HelpModal v-model="showHelpModal" />
</template>
<style lang="scss" scoped>
  main{
    height: 100%;
    position: relative;
    background: var(--cet-body-bg);
    color: var(--cet-text);
    font-family: var(--cet-font);
    .header{
      width: 100%;
      padding: 8px 12px;
      position: absolute;
      top: 0;
      left: 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      z-index: 1;
      .header-left{
        display: flex;
        align-items: center;
        .search-icon{
          font-size: 16px;
          color: var(--cet-text);
        }
        .type-select{
          margin-right: 12px;
        }
      }
      .header-right{
        display: flex;
        align-items: center;
        .help-button{
          color: var(--cet-muted);
          background: transparent;
          border: none;
          &:hover{
            color: var(--cet-text);
            background: transparent;
          }
        }
        .review-type{
          margin: 0 12px;
          opacity: 0.75;
          &:hover{ opacity: 1; }
        }
      }
      .steps{
        color: var(--cet-muted);
        &:hover{ color: var(--cet-text); }
      }
    }
  }
  .playground{
    background-color: var(--cet-play-bg);
    height: 60vh;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    letter-spacing: 12px;
    position: relative;
    transition: background-color 0.2s;
    .skill{
      width: 100%;
      position: absolute;
      bottom: 0;
      left: 0;
    }
    .char{
      width: auto;
      min-width: 30px;
      font-size: 88px;
      height: 100%;
      color: var(--cet-play-fg);
      vertical-align: middle;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0;
      transition: color 0.1s;
    }
    /* "hit" states: letter has been typed / cleared / hidden — blend
       into the playground background so it "disappears" visually. */
    .audio_char,
    .equal_char,
    .reserve_char{
      color: var(--cet-play-bg);
    }
  }
  .explain{
    font-size: 26px;
    color: var(--cet-text);
    max-width: 1000px;
    margin: 0 auto;
    .chinese{
      color: var(--cet-muted);
    }
    .mark-actions{
      margin-top: 12px;
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 13px;
    }
    .mark-btn{
      padding: 4px 12px;
      border-radius: 4px;
      border: 1px solid var(--cet-line);
      background: transparent;
      color: var(--cet-muted);
      cursor: pointer;
      font-size: 13px;
      transition: all 0.15s;
    }
    .mark-btn:hover:not(:disabled){
      border-color: var(--cet-brand);
      color: var(--cet-brand);
    }
    .mark-btn:disabled{
      color: var(--cet-brand);
      border-color: var(--cet-brand);
      opacity: 0.7;
      cursor: default;
    }
    .mark-hint{
      color: var(--cet-muted);
      font-size: 11px;
    }
    label{
      display: inline-block;
      width: 120px;
      color: var(--cet-muted);
    }
    p{
      overflow: hidden;
      display: flex;
      justify-content: space-between;
      -webkit-line-clamp: 2; /* 控制显示的行数 */
      -webkit-box-orient: vertical;
      text-overflow: ellipsis;
      white-space: normal;
      .ellipsis_word{
        display: -webkit-box;
        -webkit-line-clamp: 2; /* 控制显示的行数 */
        -webkit-box-orient: vertical;
        text-overflow: ellipsis;
        white-space: normal;
        text-align: left;
      }
    }
  }
  .explain_status{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 40vh;
  }
  .key-board{
    display: none;
  }
  .explain_result{
    text-align: center;
    padding-top: 66px;
  }
  @media screen and (max-width: 600px) {
    .playground {
      height: 24vh;
      letter-spacing: 4px;
      .char{
        min-width: 16px;
        font-size: 60px;
      }
    }
    .explain_status {
      height: calc(76vh - 250px);
      padding: 10px 14px 0;
      overflow-y: auto;
      display: block;
      .explain{
        font-size: 18px;
        p{
          margin-bottom: 2px;
        }
        .ellipsis_word{
          -webkit-line-clamp: 3; /* 控制显示的行数 */
        }
      }
      label{
        width: 48px;
        line-height: 30px;
        font-size: 16px;
      }
    }
    .key-board{
      display: block;
      padding: 6px 4px 0;
      height: 250px;
      .action{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
        span{
          border-radius: 10px 10px 0 0;
          border: 1px solid var(--cet-line);
          padding: 6px 0;
          flex: 1;
          text-align: center;
          &:active{
            background: var(--cet-surface-2);
            color: var(--cet-muted);
          }
        }
      }
      .letters{
        div{
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
          span{
            border-radius: 10px 10px 0 0;
            border: 1px solid var(--cet-line);
            padding: 10px 0;
            flex: 1;
            text-align: center;
            &:active{
              background: var(--cet-surface-2);
              color: var(--cet-muted);
            }
          }
        }
      }
    }
  }
</style>@/constant/letter

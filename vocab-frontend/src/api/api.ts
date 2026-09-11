import { request } from './request'

// /**
//  * @description -封装User类型的接口方法
//  */
// export class UserService {
//   // 模块一
//   /**
//    * @description 用户登录
//    * @param {string} username - 用户名
//    * @return {HttpResponse} result
//    */
//   static async login1(params) {
//     // 接口一
//     return request('/login', params, 'post')
//   }
//   static async login2(params) {
//     // 接口二
//     return request('/login', params, 'post')
//   }
//   static async login3(params) {
//     // 接口三
//     return request('/login', params, 'post')
//   }
// }

export class DictionaryService {
  // 模块二
  /**
   * @description 获取列表
   * @return {HttpResponse} result
   */
  static async getWordList() {
    return request('https://cdn.jsdelivr.net/gh/lyc8503/baicizhan-word-meaning-API/data/list.json', {}, 'get')
  }

  // Try baicizhan CDN first (rich data: sentence, etymology). If it fails
  // (offline / GFW / word not in baicizhan), fall back to our local /api/vocab
  // which at least gives the Chinese definition so the explain box isn't
  // blank.
  static async getWordMean(word: string) {
    try {
      const cdn: any = await request(
        `https://cdn.jsdelivr.net/gh/lyc8503/baicizhan-word-meaning-API/data/words/${word}.json`,
        {},
        'get',
      )
      if (cdn?.data) return cdn
    } catch {
      // fall through to local
    }
    for (const book of ['cet4', 'cet6']) {
      try {
        const local: any = await request(`/api/vocab/word/${book}/${word}`, {}, 'get')
        if (local?.data?.zh_full) {
          return {
            data: {
              mean_cn: local.data.zh_full || local.data.zh,
              mean_en: '',
              word_etyma: '',
              sentence: '',
              sentence_trans: '',
            },
          }
        }
      } catch {
        // try next book
      }
    }
    throw new Error(`word not found: ${word}`)
  }
}

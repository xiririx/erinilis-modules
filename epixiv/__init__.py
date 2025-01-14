import time
from nonebot import *
from . import util, pixiv, permission, download, short_url

from hoshino import Service  # 如果使用hoshino的分群管理取消注释这行

#
sv = Service('epixiv')  # 如果使用hoshino的分群管理取消注释这行

# 初始化配置文件
config = util.get_config()

db = util.init_db(config.cache_dir)
db_recommend = util.init_db(config.cache_dir, 'recommend')
# 初始化nonebot
_bot = get_bot()
admins = _bot.config.SUPERUSERS

rules = config.rules

# 初始化p站配置
epixiv = pixiv.epixiv(
    rules.refresh_day,
    rules.search_sanity_level_count
)

try:
    epixiv.auth(refresh_token=config.pixiv.refresh_token)
except Exception as e:
    print('登录p站失败了 请检查配置. %s' % e.body)


@sv.on_message('group')  # 如果使用hoshino的分群管理取消注释这行 并注释下一行的 @_bot.on_message("group")
# @_bot.on_message  # nonebot使用这
async def epixiv_main(*params):
    bot, ctx = (_bot, params[0]) if len(params) == 1 else params

    msg = str(ctx['message']).strip()
    # 搜索
    keyword = util.get_msg_keyword(config.comm.get_image_header, msg, True)
    if keyword:
        comm, footer = util.get_msg_keyword(config.comm.get_image_footer, keyword)
        keyword = await search(ctx, footer + comm)
        # await ptag(ctx, keyword)
    # 显示全部页面
    keyword = util.get_msg_keyword(config.comm.show_meta_pages, msg, True)
    if keyword:
        await show_meta_pages(ctx, keyword)
    # 相同口味
    keyword = util.get_msg_keyword(config.comm.recommend, msg, True)
    if keyword:
        await recommend(ctx, keyword)
    # ptag
    keyword = util.get_msg_keyword(config.comm.ptag, msg, True)
    if keyword:
        await ptag(ctx, keyword)


async def search(ctx, keyword: str):
    keyword = keyword.strip()
    comm = ''
    next_page = util.get_msg_keyword(config.comm.next_page, keyword)
    if next_page:
        comm, keyword = next_page
        next_page = True

    is_r18 = util.get_msg_keyword(rules.r18_flag, keyword + comm) or ''
    if is_r18:
        comm, keyword = is_r18
        is_r18 = 'r18'

    sanity_level = 6
    is_noh = util.get_msg_keyword(rules.noh_flag, keyword + comm) or ''
    if is_noh:
        comm, keyword = is_noh
        is_noh = 'noh'
        sanity_level = 2

    if not keyword:
        return ''

    uid = ctx.user_id
    is_group = ctx.detail_type == 'group'
    page_flag = str(ctx.group_id if is_group else uid)

    if is_r18 and is_group and not rules.group_r18:
        await _bot.send(ctx, '群内不许ghs')
        return ''

    ps = permission.user(uid, timeout=5 * 60)

    if ps.check() and uid not in admins:
        await _bot.send(ctx, '正在处理啦 等一等哈  %s' % ps.msg())
        return ''
    ps.running('搜索中...')
    await _bot.send(ctx, '正在搜索 请稍等')
    db_key = keyword + is_r18 + is_noh
    search_db = db.get(db_key, {})
    search_db.setdefault('create_time', time.time())
    search_db.setdefault('keyword', db_key)
    search_db.setdefault('illusts', [])
    search_db.setdefault(page_flag, 1)
    search_db = util.dict_to_object(search_db)

    illusts = search_db.illusts
    if search_db.create_time + rules.refresh_day * 24 * 60 * 60 < time.time() or not illusts:
        print('pixiv refresh cache..')
        illusts = await epixiv.search(keyword, search_sort_num=rules.search_sort_num, is_r18=bool(is_r18),
                                      sanity_level=sanity_level)
        if not illusts:
            ps.done()
            await _bot.send(ctx, '嗨呀 都没搜索到, 要不你换个搜')
            return keyword
        search_db.illusts = illusts
        db[db_key] = search_db
    else:
        print('use cache len: %s' % len(illusts))

    ps.running('下载图片中...')
    workers = rules.show_image_count
    start = 0
    if next_page:
        start = search_db[page_flag] * workers
        search_db[page_flag] += 1
        db[db_key] = search_db

    illusts = illusts[start:start + workers]

    if next_page and not illusts:
        illusts = illusts[:workers]
        search_db[page_flag] = 1
        db[db_key] = search_db

    data = await epixiv.download_illusts_img(illusts)
    ps.running('处理消息中...')
    await print_illusts(ctx, data)
    ps.done()
    return keyword


async def print_illusts(ctx, illusts):
    self_info = await _bot.call_action(action='get_login_info')
    msg_node = []
    for illust in illusts:
        image_urls = illust.image_urls
        show_image_comm = '此图有%s张, 使用下面的命令查看剩下的图\n全部图片#%s'
        original = short_url.short(image_urls.original) if config.setting.short_url_enable else image_urls.original
        # msg = {
        #     'title': illust.title,
        #     'id': illust.id,
        #     'original': show_image_comm % (len(illust.meta_pages), illust.id) if illust.meta_pages else original,
        #     'recommend': '相同口味#%s' % illust.id,
        #     'img': MessageSegment.image(illust.local_img)
        # }
        # msg_text = MessageSegment.text(config.str.print.format(**msg))
        msg_text = []
        msg_text.append(MessageSegment.text('标题：' + illust.title + '\n'))
        msg_text.append(MessageSegment.text('p站：https://pixiv.net/i/%s\n' % illust.id))
        msg_text.append(MessageSegment.text('原图：%s\n' % (show_image_comm % (len(illust.meta_pages), illust.id) if illust.meta_pages else original)))
        msg_text.append(MessageSegment.text('推荐：相同口味#%s\n' % illust.id))
        msg_text.append(MessageSegment.image(illust.local_img))

        msg_node.append(
            dict(type='node',
                 data=dict(name=self_info['nickname'],
                           uin=self_info['user_id'],
                           content=msg_text)))

    await _bot.call_action(action='send_group_forward_msg',
                           group_id=ctx.group_id,
                           messages=msg_node)



async def show_meta_pages(ctx, keyword: str):
    illust_id = util.get_illust_id(keyword)

    if not illust_id:
        return ''
    uid = ctx.user_id
    ps = permission.user(uid, timeout=5 * 60)

    if ps.check() and uid not in admins:
        await _bot.send(ctx, '正在处理啦 等一等哈  %s' % ps.msg())
        return ''
    ps.running('查找中..')
    await _bot.send(ctx, '嗯嗯, 现在就去看看')
    illust, images = epixiv.get_meta_pages(illust_id)

    if epixiv.illust_is_r18(illust) and not rules.group_r18 and ctx.detail_type == 'group':
        ps.done()
        await _bot.send(ctx, '这是限制级组图 群内不许ghs!')
        return ''

    ps.running('解密中..')
    local_list = [] 
    for img in images:
        local_list.append(await download.get_img(img))
        
    msg_node = []
    self_info = await _bot.call_action(action='get_login_info')
    for index, value in enumerate(images):
        original = short_url.short(value) if config.setting.short_url_enable else value
        # msg = {
        #     'original': original,
        #     'img': MessageSegment.image(local_list[index])
        # }
        # await _bot.send(ctx, config.str.show_meta_pages.format(**msg))
        msg_text = []
        msg_text.append(MessageSegment.text('原图: %s\n' % original))
        msg_text.append(MessageSegment.image(local_list[index]))
        msg_node.append(
            dict(type='node',
                 data=dict(name=self_info['nickname'],
                           uin=self_info['user_id'],
                           content=msg_text)))

    await _bot.call_action(action='send_group_forward_msg',
                           group_id=ctx.group_id,
                           messages=msg_node)
    ps.done()


async def recommend(ctx, keyword: str):
    illust_id = util.get_illust_id(keyword)
    if not illust_id:
        return ''

    uid = ctx.user_id
    is_group = ctx.detail_type == 'group'
    page_flag = str(ctx.group_id if is_group else uid)
    ps = permission.user(uid, timeout=5 * 60)
    # can_r18 = is_group and rules.group_r18
    can_r18 = not is_group and rules.private_r18
    if ps.check() and uid not in admins:
        await _bot.send(ctx, '正在处理啦 等一等哈  %s' % ps.msg())
        return ''
    await _bot.send(ctx, '现在就去做一份.')

    rc_db = db_recommend.get(str(illust_id), {})
    rc_db.setdefault('create_time', time.time())
    rc_db.setdefault('illust_id', str(illust_id))
    rc_db.setdefault('illusts', [])
    rc_db.setdefault(page_flag, 1)
    rc_db = util.dict_to_object(rc_db)
    illusts = rc_db.illusts
    ps.running('搜索数据中...')
    if rc_db.create_time + rules.refresh_day * 24 * 60 * 60 < time.time() or not illusts:
        print('pixiv refresh recommend cache..')
        illusts = epixiv.recommend(illust_id, can_r18=can_r18)
        if not illusts:
            ps.done()
            await _bot.send(ctx, '阿勒 , 没有什么推荐呢')
            return keyword
        rc_db.illusts = illusts
        db_recommend[keyword] = rc_db
    ps.running('下载图片中...')
    data = await epixiv.download_illusts_img(illusts[:rules.show_image_count])
    await print_illusts(ctx, data)
    ps.done()
    return ''


async def ptag(ctx, keyword: str):
    keyword = keyword.strip()
    # 关键字补全
    ac = epixiv.auto_complete(keyword)
    if ac:
        tag_info = await epixiv.get_tag_img(ac[0]['text'])
        if not tag_info:
            await _bot.send(ctx, '没有搜索到标签信息呢')
            return
        ac_str = '\n'.join(map(lambda x: '%s  %s' % (x['translation'], x['text']), ac))
        tag_info['local_img'] = MessageSegment.image(tag_info['local_img'])
        tag_info['ac'] = ac_str
        await _bot.send(ctx, config.str.auto_complete.format(**tag_info))

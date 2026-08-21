'use strict';

// Frida hook for a future, authorized official-client trace. It never emits raw
// packet bytes or secret strings; channel-0 buffers are reduced in memory to
// structural metadata and then discarded.

const LIBRARY = 'libPPPP_API.so';
const MAX_MESSAGES = 5;
const startedAt = Date.now();
const pendingReads = new Map();
let writeCount = 0;
let readCount = 0;
let installed = false;

function relativeMs() {
  return Date.now() - startedAt;
}

function emit(event) {
  send(Object.assign({ schema: 'yi_tnp_trace/v1', relative_ms: relativeMs() }, event));
}

function u8(pointer, offset) {
  return pointer.add(offset).readU8();
}

function u16be(pointer, offset) {
  return (u8(pointer, offset) << 8) | u8(pointer, offset + 1);
}

function u32be(pointer, offset) {
  return (
    u8(pointer, offset) * 0x1000000 +
    (u8(pointer, offset + 1) << 16) +
    (u8(pointer, offset + 2) << 8) +
    u8(pointer, offset + 3)
  ) >>> 0;
}

function s32(value) {
  return value > 0x7fffffff ? value - 0x100000000 : value;
}

function boundedCStringLength(pointer, limit) {
  if (pointer.isNull()) return { state: 'MISSING', length: 0, truncated: false };
  try {
    for (let index = 0; index < limit; index += 1) {
      if (u8(pointer, index) === 0) {
        return { state: 'PRESENT', length: index, truncated: false };
      }
    }
    return { state: 'PRESENT', length: limit, truncated: true };
  } catch (_) {
    return { state: 'PRESENT', length: null, truncated: true };
  }
}

function authShape(pointer) {
  let length = 32;
  let comma = -1;
  let leftIsAlphanumeric = true;
  for (let index = 0; index < 32; index += 1) {
    const value = u8(pointer, index);
    if (value === 0) {
      length = index;
      break;
    }
    if (value === 44 && comma < 0) {
      comma = index;
    } else if (comma < 0) {
      const isAlphaNumeric =
        (value >= 48 && value <= 57) ||
        (value >= 65 && value <= 90) ||
        (value >= 97 && value <= 122);
      leftIsAlphanumeric = leftIsAlphanumeric && isAlphaNumeric;
    }
  }
  const isNonceShape = comma === 15 && leftIsAlphanumeric;
  return {
    field_size: 32,
    actual_length: length,
    nonce_length: isNonceShape ? comma : null,
    hmac_component_length: isNonceShape ? length - comma - 1 : null,
    null_terminated: length < 32,
  };
}

function outerShape(pointer) {
  return {
    size: 8,
    application_version: u8(pointer, 0),
    stream_type: u8(pointer, 1),
    ability_or_reserved: u8(pointer, 2),
    reserved: u8(pointer, 3),
    data_size: u32be(pointer, 4),
  };
}

function ioctrlShape(pointer, direction) {
  const command = u16be(pointer, 0);
  const result = {
    size: 40,
    command: command,
    command_number: u16be(pointer, 2),
    ex_header_size: u16be(pointer, 4),
    data_size: u16be(pointer, 6),
  };
  if (direction === 'WRITE') {
    result.auth = authShape(pointer.add(8));
  } else {
    result.auth_result = s32(u32be(pointer, 8));
  }
  return result;
}

function safePayloadShape(command, pointer, length) {
  const result = { length: length };
  if (command === 9029 && length >= 4) {
    result.start_realtime = {
      use_count: u8(pointer, 0),
      resolution: u8(pointer, 1),
      command_version: u8(pointer, 2),
      reserved: u8(pointer, 3),
    };
  }
  return result;
}

function parseWholePacket(pointer, length, direction) {
  if (length < 48) throw new Error('packet_too_short');
  const outer = outerShape(pointer);
  const ioctrl = ioctrlShape(pointer.add(8), direction);
  const payloadOffset = 48 + ioctrl.ex_header_size;
  if (payloadOffset + ioctrl.data_size > length) throw new Error('declared_size_exceeds_buffer');
  return {
    total_length: length,
    outer: outer,
    ioctrl: ioctrl,
    payload: safePayloadShape(ioctrl.command, pointer.add(payloadOffset), ioctrl.data_size),
  };
}

function parseReadBody(pointer, length, outer) {
  if (length < 40) throw new Error('ioctrl_body_too_short');
  const ioctrl = ioctrlShape(pointer, 'READ');
  const payloadOffset = 40 + ioctrl.ex_header_size;
  if (payloadOffset + ioctrl.data_size > length) throw new Error('declared_size_exceeds_buffer');
  return {
    total_length: 8 + length,
    outer: outer,
    ioctrl: ioctrl,
    payload: safePayloadShape(ioctrl.command, pointer.add(payloadOffset), ioctrl.data_size),
  };
}

function findExport(name) {
  const module = Process.findModuleByName(LIBRARY);
  return module === null ? null : module.findExportByName(name);
}

function hookFunction(name, callbacks) {
  const address = findExport(name);
  if (address === null) return false;
  Interceptor.attach(address, callbacks);
  return true;
}

function installConnectionHooks() {
  hookFunction('PPPP_Initialize', {
    onEnter(args) {
      this.input = boundedCStringLength(args[0], 4096);
      this.maxSessions = args[1].toInt32();
    },
    onLeave(retval) {
      emit({
        kind: 'native_connection',
        function: 'PPPP_Initialize',
        layer: 'C',
        input: this.input,
        max_sessions: this.maxSessions,
        return_code: retval.toInt32(),
      });
    },
  });

  hookFunction('Java_com_p2p_pppp_1api_PPPP_1APIs_PPPP_1Initialize', {
    onEnter(args) {
      this.length = null;
      try {
        this.length = Java.vm.getEnv().getArrayLength(args[2]);
      } catch (_) {}
      this.maxSessions = args[3].toInt32();
    },
    onLeave(retval) {
      emit({
        kind: 'native_connection',
        function: 'PPPP_Initialize',
        layer: 'JNI',
        input: { state: 'PRESENT', length: this.length },
        max_sessions: this.maxSessions,
        return_code: retval.toInt32(),
      });
    },
  });

  ['PPPP_Connect', 'PPPP_ConnectByServer', 'PPPP_WakeUp_And_Connect'].forEach((name) => {
    hookFunction(name, {
      onEnter(args) {
        this.name = name;
        this.flag = args[1].toInt32() & 0xff;
        this.udpPort = args[2].toInt32();
        this.did = boundedCStringLength(args[0], 256);
        this.server = boundedCStringLength(args[3], 4096);
        this.license = boundedCStringLength(args[4], 512);
      },
      onLeave(retval) {
        emit({
          kind: 'native_connection',
          function: this.name,
          flag: this.flag,
          udp_port: this.udpPort,
          did: this.did,
          server_or_init_string: this.server,
          license_or_device_key: this.license,
          return_code: retval.toInt32(),
        });
      },
    });
  });

  hookFunction('PPPP_Check', {
    onEnter(args) {
      this.session = args[0].toInt32();
    },
    onLeave(retval) {
      emit({
        kind: 'native_connection',
        function: 'PPPP_Check',
        session: this.session,
        return_code: retval.toInt32(),
      });
    },
  });
}

function installWriteHook() {
  hookFunction('PPPP_Write', {
    onEnter(args) {
      this.session = args[0].toInt32();
      this.channel = args[1].toInt32() & 0xff;
      this.length = args[3].toInt32();
      this.event = null;
      if (this.channel !== 0 || writeCount >= MAX_MESSAGES) return;
      try {
        this.event = Object.assign(
          { kind: 'channel_0', direction: 'WRITE', session: this.session, channel: 0 },
          parseWholePacket(args[2], this.length, 'WRITE')
        );
      } catch (error) {
        this.event = {
          kind: 'channel_0',
          direction: 'WRITE',
          session: this.session,
          channel: 0,
          total_length: this.length,
          parser_failure: String(error.message || error),
        };
      }
    },
    onLeave(retval) {
      if (this.event === null) return;
      this.event.return_code = retval.toInt32();
      writeCount += 1;
      this.event.ordinal = writeCount;
      emit(this.event);
    },
  });
}

function installReadHook() {
  hookFunction('PPPP_Read', {
    onEnter(args) {
      this.session = args[0].toInt32();
      this.channel = args[1].toInt32() & 0xff;
      this.buffer = args[2];
      this.sizePointer = args[3];
    },
    onLeave(retval) {
      if (this.channel !== 0 || readCount >= MAX_MESSAGES) return;
      const returnCode = retval.toInt32();
      if (returnCode < 0) {
        if (returnCode !== -3003 && returnCode !== -3014) {
          readCount += 1;
          emit({
            kind: 'channel_0',
            direction: 'READ',
            ordinal: readCount,
            session: this.session,
            channel: 0,
            total_length: 0,
            return_code: returnCode,
          });
        }
        return;
      }

      let length;
      try {
        length = this.sizePointer.readS32();
      } catch (_) {
        return;
      }
      const key = String(this.session);
      try {
        if (length >= 48) {
          readCount += 1;
          emit(Object.assign(
            {
              kind: 'channel_0', direction: 'READ', ordinal: readCount,
              session: this.session, channel: 0, return_code: returnCode,
            },
            parseWholePacket(this.buffer, length, 'READ')
          ));
          return;
        }
        if (length === 8) {
          pendingReads.set(key, outerShape(this.buffer));
          return;
        }
        const outer = pendingReads.get(key);
        if (outer === undefined) return;
        pendingReads.delete(key);
        readCount += 1;
        emit(Object.assign(
          {
            kind: 'channel_0', direction: 'READ', ordinal: readCount,
            session: this.session, channel: 0, return_code: returnCode,
          },
          parseReadBody(this.buffer, length, outer)
        ));
      } catch (error) {
        pendingReads.delete(key);
        readCount += 1;
        emit({
          kind: 'channel_0',
          direction: 'READ',
          ordinal: readCount,
          session: this.session,
          channel: 0,
          total_length: length,
          return_code: returnCode,
          parser_failure: String(error.message || error),
        });
      }
    },
  });
}

function install() {
  if (installed || Process.findModuleByName(LIBRARY) === null) return false;
  installConnectionHooks();
  installWriteHook();
  installReadHook();
  installed = true;
  emit({ kind: 'instrumentation', state: 'READY', library: LIBRARY });
  return true;
}

if (!install()) {
  const timer = setInterval(() => {
    if (install()) clearInterval(timer);
  }, 250);
}

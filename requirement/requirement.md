# 🧪 BÀI TEST KỸ THUẬT: XÂY DỰNG CỖ MÁY AI PROFILER & TÂM SỰ TỈ TÊ TỰ HÀNH THAY THẾ TRỢ LÝ CSKH (TES-3808)
## VỊ TRÍ ỨNG TUYỂN: AI ENGINEER / AGENTIC SYSTEM ARCHITECT
**Đơn vị ban hành:** Ban Sáng Lập WeAction100X Holding & Dr.Bee  
**Thời gian hoàn thành:** Trong vòng 24 - 48 giờ kể từ khi nhận đề.  
**Mục tiêu bài test:** Đo lường năng lực kiến trúc hệ thống, tư duy giải quyết vấn đề từ nguyên lý gốc (First Principles) và năng lực lập trình Agentic AI thực chiến.

---

## 🎯 1. BỐI CẢNH DỰ ÁN & BÀI TOÁN GỐC (DIRECT FROM ISSUE TES-3808)

### Bối cảnh:
Dr.Bee là thương hiệu Dược mỹ phẩm chuyên sâu về phục hồi nang tóc và da đầu tốc độ cao. Hàng ngày, hệ thống tiếp nhận hàng ngàn khách hàng tiềm năng tương tác qua Fanpage/Mạng xã hội. 

Trước đây, doanh nghiệp phải thuê đội ngũ Trợ lý Chăm sóc Khách hàng (CSKH) con người để:
1. Vào Facebook của khách hàng, xem thông tin và hình ảnh cá nhân.
2. Tự suy đoán hoàn cảnh sống, độ tuổi, tâm lý của khách.
3. Nhắn tin tâm sự, làm quen, tạo thiện cảm trước khi chuyển giao cho Dược sĩ tư vấn chuyên sâu.

**Nhược điểm của nhân sự con người:**
- Tốc độ quá chậm (mất 2 - 3 phút để xem xét 1 trang cá nhân, tối đa chỉ xử lý được 30 - 50 khách/ca làm việc).
- Chi phí vận hành cao, dễ sót khách và chất lượng nói chuyện không đồng đều, thường mắc lỗi nóng vội chào bán sản phẩm khiến khách hàng e dè, đề phòng.

### Đề bài trực tiếp từ Ban Sáng Lập (Issue TES-3808):
> *"Cần xây dựng một tính năng/Agent tự động vào Facebook của khách tổng hợp thông tin cá nhân của khách để cho bot lấy thông tin này. Trước khi tư vấn gì thì sẽ tâm sự tỉ tê với khách dựa trên thông tin này trước. Dòng 5-10 tin nhắn đầu tiên chỉ để tâm sự tỉ tê với khách về chủ đề trên trang cá nhân của khách và những gì mà khách quan tâm. Hãy nói những gì mà họ muốn nghe chứ đừng nói cái thứ gì mà bot muốn bán. Và 20h tối hàng ngày -> dùng thông tin đó, nhắn 1 câu chuyện mồi dựa vào các thông tin trên trang cá nhân của khách => Để lấy thêm điểm chạm.*
> 
> *Mục tiêu tối thượng: Cỗ máy này phải THAY THẾ HOÀN TOÀN đội ngũ Trợ lý CSKH con người!"*

---

## 📋 2. YÊU CẦU CHỨC NĂNG CỐT LÕI (CORE REQUIREMENTS)

Bạn được tự do lựa chọn công nghệ, ngôn ngữ (ưu tiên Python hoặc TypeScript/Node.js) và các mô hình AI/LLM để giải bài toán. Hệ thống của bạn cần đáp ứng 3 chức năng chính:

### 🔹 Chức năng 1: Customer Profile Intelligence (Đọc vị trang cá nhân)
- Tiếp nhận thông tin định danh của khách hàng (URL trang Facebook cá nhân, ví dụ: `https://www.facebook.com/username` hoặc `https://www.facebook.com/profile.php?id=...`, hoặc dữ liệu profile trích xuất được).
- Tự động trích xuất các dữ liệu công khai có thật: Tên hiển thị, các thông tin trong tiểu sử (Bio), và đặc biệt là **ngữ cảnh từ hình ảnh đại diện (Avatar) hoặc hình ảnh công khai gần nhất** (ví dụ: ảnh mẹ bế con nhỏ, ảnh gia đình, ảnh chân dung công sở, ảnh chụp cùng cúp/bằng khen, ảnh hiệu ứng filter, v.v.).

### 🔹 Chức năng 2: 5-10 Empathy Rapport Dialogues (Chuỗi 5-10 tin nhắn tâm sự tỉ tê)
- Tạo ra kịch bản chuỗi 5 đến 10 tin nhắn đầu tiên để bot trò chuyện với khách hàng.
- **LUẬT THÉP BẤT BIẾN (Zero-Sales Rule):**
  - Tuyệt đối **0% CHÀO BÁN SẢN PHẨM**, không nhắc đến tên thương hiệu Dr.Bee, không nói về giá cả hay mời mọc mua hàng trong chuỗi tin nhắn này.
  - Phải tập trung 100% vào việc "nói điều khách hàng muốn nghe": Tôn vinh nét đẹp, đồng cảm với sự vất vả chăm lo cho gia đình/con cái, sẻ chia áp lực công việc, khen ngợi thần thái tích cực của khách... tạo cảm giác như một người bạn tâm giao ấm áp, chân thành.

### 🔹 Chức năng 3: 20h Evening Hook (Câu chuyện mồi điểm chạm lúc 20h tối)
- Thiết kế 1 thông điệp mở đầu trò chuyện (Icebreaker Hook) được gửi vào khung giờ vàng **20h00 tối**.
- Nội dung mồi câu chuyện phải dựa trên chính dữ liệu thật từ trang cá nhân của khách (ví dụ: hỏi thăm bữa cơm tối gia đình, hỏi thăm các bé sau một ngày đi học, hay chia sẻ khoảnh khắc thư giãn sau giờ làm việc).

---

## 💻 3. ĐẶC TẢ ĐẦU VÀO & ĐẦU RA CHI TIẾT (INPUT / OUTPUT SPECIFICATIONS)

### 🔹 Cách thức chạy (CLI Command):
Agent của bạn phải có khả năng thực thi độc lập từ dòng lệnh Terminal:
```bash
python main.py --url "https://www.facebook.com/example_user"
# Hoặc: npm start -- --url "https://www.facebook.com/example_user"
```

### 🔹 Đầu ra bắt buộc (Strict JSON Output):
Hệ thống bắt buộc phải xuất ra màn hình Terminal (và ghi vào file `output.json`) đúng **1 chuỗi JSON hợp lệ (Strict JSON)**, có thể parse trực tiếp bằng `json.loads()`, tuân thủ cấu trúc sau:

```json
{
  "status": "SUCCESS",
  "facebook_url": "https://www.facebook.com/example_user",
  "profile_data": {
    "customer_name": "Tên trích xuất được từ profile",
    "visual_context": "Mô tả ngắn gọn, chính xác bối cảnh hình ảnh trích xuất được (VD: Ảnh mẹ bế con nhỏ mặc áo thun xanh bên bánh sinh nhật / Ảnh chân dung mặc blazer công sở...)",
    "estimated_demographics": {
      "gender": "Nữ / Nam",
      "estimated_age_range": "25 - 35 tuổi",
      "apparent_lifestyle": "Mẹ bỉm chăm con / Dân văn phòng bận rộn / Doanh nhân tự do..."
    }
  },
  "ethical_rapport": {
    "core_empathy_angle": "Góc độ thấu cảm chính (VD: Tôn vinh sự hy sinh của người mẹ lo toan cho con cái)",
    "dialogue_sequence_10": [
      "Tin nhắn 1: Lời chào ấm áp kèm ấn tượng đầu tiên về ảnh đại diện của khách...",
      "Tin nhắn 2: Khơi gợi tâm sự tự nhiên về gia đình/con cái hoặc công việc...",
      "Tin nhắn 3: ...",
      "Tin nhắn 4: ...",
      "Tin nhắn 5: ..."
    ],
    "sales_mention_check": "ZERO_SALES_CONFIRMED"
  },
  "evening_cadence_20pm": {
    "trigger_time": "20:00",
    "evening_hook_message": "Câu chuyện mồi gửi lúc 20h tối: Nhẹ nhàng, ân cần, chạm đúng hoàn cảnh của khách để khơi gợi khách trả lời tự nhiên mà không tạo cảm giác bị làm phiền."
  }
}
```

---

## 🧪 4. NGUYÊN TẮC KIỂM THỬ THỰC NGHIỆM (ZERO FACT INVENTION)

Đúng theo chỉ đạo của Ban Sáng Lập:
> *"Tuyệt đối không được phép bốc phét, nếu không đọc được thì thông báo rõ là không đọc được, không được để AI tự bịa thông tin cá nhân của khách!"*

- **Quy tắc trung thực dữ liệu (Zero Hallucination):** Dữ liệu phân tích và câu chuyện mồi phải bắt nguồn từ dữ liệu thật thu thập được từ URL Facebook đó. 
- **Xử lý tài khoản khóa kín (Private / Dead Link):** Nếu URL Facebook bị khóa kín hoàn toàn (Private) hoặc không thu thập được hình ảnh, bot phải trả về trạng thái rõ ràng:
  ```json
  {
    "status": "PARTIAL_OR_PRIVATE",
    "facebook_url": "...",
    "error_note": "Trang cá nhân bị khóa riêng tư, chỉ thu thập được metadata công khai..."
  }
  ```
  Tuyệt đối không được bịa đặt ảnh hay hoàn cảnh nếu trang cá nhân không có dữ liệu đó.

---

## 📦 5. HỒ SƠ NỘP BÀI & TIÊU CHUẨN NGHIỆM THU

### 1. Hồ sơ nộp bài gồm:
1. **Đường link GitHub Repository**:
   - Chứa toàn bộ mã nguồn sạch sẽ, tổ chức theo kiến trúc module.
   - Có file `requirements.txt` (hoặc `package.json`).
   - Có file `README.md` hướng dẫn cấu hình môi trường và chạy thử đúng **1 lệnh duy nhất**.
2. **File nhật ký kết quả chạy thử (`test_results.json` hoặc `test_run.log`)**:
   - In ra kết quả chạy thực tế thành công trên ít nhất **3 đường link Facebook cá nhân khác nhau** do bạn tự chọn thử nghiệm (Ví dụ: 1 link của bạn, 1 link người thân/bạn bè, 1 link người nổi tiếng hoặc khách hàng công khai).

### 2. Tiêu chuẩn đánh giá của Ban Sáng Lập:
- **Tính khả thi & Chạy thật (Runability)**: Chương trình tải về chạy mượt mà ngay trên máy của Ban Lãnh Đạo, không lỗi vặt, không crash.
- **Tư duy kiến trúc hệ thống (System Architecture)**: Cách bạn xử lý bài toán tiếp cận dữ liệu Facebook mà không bị chặn, cách thiết kế luồng pipeline kết nối giữa dữ liệu và mô hình AI.
- **Chất lượng nội dung giao tiếp (Emotional Intelligence)**: Chuỗi tin nhắn và câu chuyện mồi lúc 20h phải có chiều sâu cảm xúc, ngôn từ tinh tế, ấm áp, thấu hiểu tâm lý phụ nữ/khách hàng trung niên, vượt trội so với câu từ vô hồn của bot thông thường.
- **Thời hạn hoàn thành**: Nộp bài trong vòng **24 - 48 giờ** kể từ khi nhận được đề bài.

Chúc bạn thể hiện xuất sắc bản lĩnh công nghệ và năng lực giải quyết vấn đề của mình!
